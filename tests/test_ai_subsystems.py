import asyncio
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from xyberos.kernel import (
    DependencyContainer,
    ExecutionContext,
    ExecutionContextAccessor,
    PolicyEngine,
)
from xyberos.providers.ai import ModelProviderError, OpenAICompatibleProvider
from xyberos.providers.knowledge import InMemoryKnowledgeProvider
from xyberos.providers.memory import InMemoryMemoryProvider, new_memory_message
from xyberos.subsystems.ai import (
    AISubsystem,
    IntentResolver,
    IntentSubsystem,
    ModelMessage,
    ModelProvider,
    ModelResponse,
)
from xyberos.subsystems.knowledge import (
    KnowledgeDocument,
    KnowledgeProvider,
    KnowledgeSubsystem,
)
from xyberos.subsystems.flows import (
    ExecutionPolicy,
    FlowDefinition,
    FlowEngine,
    FlowStep,
)
from xyberos.subsystems.memory import (
    MemoryProvider,
    MemoryScope,
    MemorySubsystem,
)


class FakeModelProvider(ModelProvider):
    def __init__(self, content):
        self.content = content
        self.last_messages = ()
        self.last_options = {}
        self.closed = False
        self.call_count = 0

    @property
    def provider_name(self):
        return "fake"

    async def initialize(self, config):
        self.config = config

    async def close(self):
        self.closed = True

    async def generate(
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        response_format=None,
    ):
        self.call_count += 1
        self.last_messages = tuple(messages)
        self.last_options = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
        }
        return ModelResponse(self.content, model or "fake-model", self.provider_name)


class FakePolicyEngine(PolicyEngine):
    def __init__(self, allowed):
        self.allowed = allowed
        self.calls = []

    async def authorize(self, context, capability, resource=None):
        self.calls.append((context, capability, resource))
        return self.allowed


class TestAISubsystems(unittest.TestCase):
    def test_ai_subsystem_requires_an_application_policy_engine(self):
        async def scenario():
            provider = FakeModelProvider("{}")
            subsystem = AISubsystem(provider)
            with self.assertRaisesRegex(RuntimeError, "PolicyEngine"):
                await subsystem.initialize({"config": {}}, DependencyContainer())
            self.assertFalse(provider.closed)

        asyncio.run(scenario())

    def test_ai_subsystem_selects_provider_and_unregisters_on_shutdown(self):
        async def scenario():
            provider = FakeModelProvider("{}")
            subsystem = AISubsystem(provider)
            container = DependencyContainer()
            container.register_utility(PolicyEngine, FakePolicyEngine(True))
            await subsystem.initialize({"config": {}}, container)
            self.assertEqual(
                container.resolve(ModelProvider).provider_name,
                provider.provider_name,
            )
            self.assertIsNot(container.resolve(ModelProvider), provider)
            await subsystem.shutdown()
            self.assertTrue(provider.closed)
            with self.assertRaises(KeyError):
                container.resolve(ModelProvider)

        asyncio.run(scenario())

    def test_intent_resolution_validates_model_output_and_uses_allowlist(self):
        async def scenario():
            provider = FakeModelProvider(
                '{"name":"search","parameters":{"query":"weather"},"confidence":0.8}'
            )
            subsystem = IntentSubsystem()
            container = DependencyContainer()
            policy = FakePolicyEngine(True)
            container.register_utility(PolicyEngine, policy)
            ai_subsystem = AISubsystem(provider)
            await ai_subsystem.initialize({"config": {}}, container)
            await subsystem.initialize(
                {"allowed_intents": ["search", "help"], "model": "small-model"},
                container,
            )
            resolver = container.resolve(IntentResolver)
            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                intent = await resolver.resolve("Find the weather")
            finally:
                ExecutionContextAccessor.reset(token)
            self.assertEqual(intent.name, "search")
            self.assertEqual(intent.parameters, {"query": "weather"})
            self.assertEqual(intent.confidence, 0.8)
            self.assertEqual(provider.last_options["temperature"], 0)
            self.assertEqual(
                provider.last_options["response_format"],
                {"type": "json_object"},
            )
            self.assertEqual(provider.last_messages[-1].content, "Find the weather")
            self.assertEqual(policy.calls[0][1].name, "ai.generate")
            await subsystem.shutdown()
            await ai_subsystem.shutdown()

        asyncio.run(scenario())

    def test_intent_rejects_unknown_name_and_malformed_output(self):
        async def scenario():
            provider = FakeModelProvider(
                '{"name":"delete_everything","parameters":{},"confidence":1}'
            )
            subsystem = IntentSubsystem()
            ai_subsystem = AISubsystem(provider)
            container = DependencyContainer()
            container.register_utility(PolicyEngine, FakePolicyEngine(True))
            await ai_subsystem.initialize({"config": {}}, container)
            await subsystem.initialize({"allowed_intents": ["search"]}, container)
            resolver = container.resolve(IntentResolver)
            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                with self.assertRaisesRegex(ValueError, "not allowed"):
                    await resolver.resolve("do something")

                provider.content = '{"name":"search","parameters":[],"confidence":1}'
                with self.assertRaisesRegex(ValueError, "parameters"):
                    await resolver.resolve("search")
            finally:
                ExecutionContextAccessor.reset(token)
            await subsystem.shutdown()
            await ai_subsystem.shutdown()

        asyncio.run(scenario())

    def test_model_provider_requires_execution_context_and_policy_approval(self):
        async def scenario():
            provider = FakeModelProvider("ok")
            subsystem = AISubsystem(provider)
            container = DependencyContainer()
            policy = FakePolicyEngine(False)
            container.register_utility(PolicyEngine, policy)
            await subsystem.initialize({"config": {}}, container)
            guarded = container.resolve(ModelProvider)
            with self.assertRaisesRegex(PermissionError, "trusted execution context"):
                await guarded.generate((ModelMessage("user", "hello"),))

            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                with self.assertRaisesRegex(PermissionError, "Policy denied"):
                    await guarded.generate((ModelMessage("user", "hello"),))
            finally:
                ExecutionContextAccessor.reset(token)
            self.assertEqual(provider.call_count, 0)
            await subsystem.shutdown()

        asyncio.run(scenario())

    def test_flow_uses_guarded_model_provider_with_authorization(self):
        async def scenario():
            provider = FakeModelProvider("model answer")
            subsystem = AISubsystem(provider)
            container = DependencyContainer()
            policy = FakePolicyEngine(True)
            container.register_utility(PolicyEngine, policy)
            await subsystem.initialize({"config": {}}, container)
            guarded_provider = container.resolve(ModelProvider)
            engine = FlowEngine(dependencies={"model": guarded_provider})

            async def generate(state):
                result = await state.dependencies["model"].generate(
                    (ModelMessage("user", state.input),)
                )
                return result.content

            flow = FlowDefinition(
                "assist",
                (FlowStep("generate", generate, policy=ExecutionPolicy.ASYNC),),
            )
            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                result = await engine.run(flow, "hello")
            finally:
                ExecutionContextAccessor.reset(token)
            self.assertEqual(result.state.outputs["generate"], "model answer")
            self.assertEqual(policy.calls[0][1].name, "ai.generate")
            await subsystem.shutdown()

        asyncio.run(scenario())

    def test_memory_is_bounded_and_scoped_by_tenant_actor_and_conversation(self):
        async def scenario():
            provider = InMemoryMemoryProvider()
            subsystem = MemorySubsystem(provider)
            container = DependencyContainer()
            await subsystem.initialize(
                {
                    "config": {
                        "max_messages": 2,
                        "max_conversations": 1,
                        "max_message_chars": 5,
                    }
                },
                container,
            )
            memory = container.resolve(MemoryProvider)
            scope = MemoryScope("tenant-a", "actor-a", "conversation-a")
            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                await memory.append(scope, new_memory_message("user", "one"))
                await memory.append(scope, new_memory_message("assistant", "two"))
                await memory.append(scope, new_memory_message("user", "three"))
                self.assertEqual(
                    [message.content for message in await memory.list_messages(scope)],
                    ["two", "three"],
                )
                unauthorized_scope = MemoryScope(
                    "tenant-b",
                    "actor-a",
                    "conversation-a",
                )
                with self.assertRaisesRegex(PermissionError, "does not match"):
                    await memory.list_messages(unauthorized_scope)
                other_scope = MemoryScope(
                    "tenant-a",
                    "actor-a",
                    "conversation-b",
                )
                self.assertEqual(await memory.list_messages(other_scope), ())
                await memory.append(other_scope, new_memory_message("user", "other"))
                self.assertEqual(await memory.list_messages(scope), ())
                with self.assertRaisesRegex(ValueError, "max_message_chars"):
                    await memory.append(scope, new_memory_message("user", "too long"))
            finally:
                await subsystem.shutdown()
                try:
                    with self.assertRaises(RuntimeError):
                        await memory.list_messages(scope)
                finally:
                    ExecutionContextAccessor.reset(token)

        asyncio.run(scenario())

    def test_knowledge_retrieval_enforces_tenant_actor_and_source_scope(self):
        async def scenario():
            provider = InMemoryKnowledgeProvider()
            subsystem = KnowledgeSubsystem(provider)
            container = DependencyContainer()
            await subsystem.initialize({"config": {}}, container)
            knowledge = container.resolve(KnowledgeProvider)
            await knowledge.put(
                KnowledgeDocument(
                    "manual",
                    "tenant-a",
                    "The secure account recovery process verifies identity.",
                    frozenset({"actor-a"}),
                    {"title": "Recovery manual"},
                )
            )
            await knowledge.put(
                KnowledgeDocument(
                    "private",
                    "tenant-a",
                    "The secure recovery code is restricted.",
                    frozenset({"actor-b"}),
                )
            )
            await knowledge.put(
                KnowledgeDocument(
                    "other-tenant",
                    "tenant-b",
                    "The secure recovery policy is different.",
                )
            )
            token = ExecutionContextAccessor.set(
                ExecutionContext("request-a", "tenant-a", "actor-a")
            )
            try:
                results = await knowledge.search(
                    tenant_id="tenant-a",
                    actor_id="actor-a",
                    query="secure recovery",
                )
                with self.assertRaisesRegex(PermissionError, "does not match"):
                    await knowledge.search(
                        tenant_id="tenant-b",
                        actor_id="actor-a",
                        query="secure recovery",
                    )
                self.assertEqual(
                    await knowledge.search(
                        tenant_id="tenant-a",
                        actor_id="actor-a",
                        query="secure recovery",
                        allowed_sources={"private"},
                    ),
                    (),
                )
            finally:
                ExecutionContextAccessor.reset(token)
            self.assertEqual([result.source_id for result in results], ["manual"])
            self.assertIn("identity", results[0].excerpt)
            self.assertEqual(results[0].metadata["title"], "Recovery manual")
            await subsystem.shutdown()

        asyncio.run(scenario())

    def test_knowledge_provider_enforces_capacity_limits(self):
        async def scenario():
            provider = InMemoryKnowledgeProvider()
            await provider.initialize(
                {"max_documents": 1, "max_document_chars": 10}
            )
            await provider.put(KnowledgeDocument("one", "tenant", "small text"))
            with self.assertRaisesRegex(ValueError, "max_documents"):
                await provider.put(KnowledgeDocument("two", "tenant", "small text"))
            with self.assertRaisesRegex(ValueError, "max_document_chars"):
                await provider.put(
                    KnowledgeDocument("one", "tenant", "this is too long")
                )
            await provider.close()

        asyncio.run(scenario())


class TestOpenAICompatibleProvider(unittest.TestCase):
    def test_ollama_is_the_default_endpoint_and_model(self):
        self.assertEqual(
            OpenAICompatibleProvider.DEFAULT_BASE_URL,
            "http://localhost:11434/v1",
        )
        self.assertEqual(OpenAICompatibleProvider.DEFAULT_MODEL, "llama3.2")

    def test_non_loopback_model_endpoint_requires_https(self):
        async def scenario():
            provider = OpenAICompatibleProvider()
            with self.assertRaisesRegex(ValueError, "must use HTTPS"):
                await provider.initialize(
                    {
                        "base_url": "http://model.example.invalid/v1",
                    }
                )

        asyncio.run(scenario())

    def test_request_character_and_output_token_limits_are_enforced(self):
        async def scenario():
            provider = OpenAICompatibleProvider()
            await provider.initialize(
                {
                    "base_url": "http://127.0.0.1:1/v1",
                    "model": "test-model",
                    "max_input_chars": 4,
                    "max_output_tokens": 8,
                }
            )
            try:
                with self.assertRaisesRegex(ValueError, "max_input_chars"):
                    await provider.generate((ModelMessage("user", "hello"),))
                with self.assertRaisesRegex(ValueError, "max_output_tokens"):
                    await provider.generate(
                        (ModelMessage("user", "hey"),),
                        max_tokens=9,
                    )
            finally:
                await provider.close()

        asyncio.run(scenario())

    def test_model_request_does_not_follow_endpoint_redirects(self):
        requests_received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                requests_received.append(self.path)
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/redirected")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):
                del format, args

        async def scenario():
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            provider = OpenAICompatibleProvider()
            try:
                await provider.initialize(
                    {"base_url": f"http://127.0.0.1:{server.server_port}/v1"}
                )
                with self.assertRaisesRegex(ModelProviderError, "HTTP 302"):
                    await provider.generate(
                        (ModelMessage("user", "hello"),),
                        model="test-model",
                    )
                self.assertEqual(requests_received, ["/v1/chat/completions"])
            finally:
                await provider.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        asyncio.run(scenario())

    def test_local_openai_compatible_request_round_trip(self):
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                received["authorization"] = self.headers.get("Authorization")
                received["body"] = json.loads(body)
                response = json.dumps(
                    {
                        "model": "local-model",
                        "choices": [
                            {
                                "message": {"role": "assistant", "content": "ready"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 4,
                            "completion_tokens": 1,
                            "total_tokens": 5,
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format, *args):
                del format, args

        async def scenario():
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            provider = OpenAICompatibleProvider()
            try:
                await provider.initialize(
                    {
                        "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                        "api_key": "test-only",
                        "model": "configured-model",
                    }
                )
                response = await provider.generate(
                    (ModelMessage("user", "hello"),),
                    response_format={"type": "json_object"},
                    max_tokens=64,
                )
                self.assertEqual(response.content, "ready")
                self.assertEqual(response.model, "local-model")
                self.assertEqual(response.usage["total_tokens"], 5)
                self.assertEqual(received["authorization"], "Bearer test-only")
                self.assertEqual(
                    received["body"]["response_format"],
                    {"type": "json_object"},
                )
                self.assertEqual(received["body"]["max_tokens"], 64)
                self.assertEqual(received["body"]["model"], "configured-model")

                default_provider = OpenAICompatibleProvider()
                await default_provider.initialize(
                    {"base_url": f"http://127.0.0.1:{server.server_port}/v1"}
                )
                try:
                    default_response = await default_provider.generate(
                        (ModelMessage("user", "default"),)
                    )
                    self.assertEqual(default_response.content, "ready")
                    self.assertEqual(received["body"]["model"], "llama3.2")
                    self.assertIsNone(received["authorization"])
                finally:
                    await default_provider.close()
            finally:
                await provider.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
