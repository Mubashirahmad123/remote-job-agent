"""Exercise the real CrewAI API after the deliberate security compatibility rollback.

No providers, Sheets, scraper, credentials or production .env are used. Extract
only the production factory AST because importing main.py requires personal
configuration before it defines that factory.
"""
import ast
from importlib.metadata import requires, version
from pathlib import Path
import socket

from packaging.requirements import Requirement
from packaging.version import Version
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def offline_sdk(monkeypatch):
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    monkeypatch.setenv('CREWAI_TELEMETRY_DISABLED', 'true')
    monkeypatch.setenv('CREWAI_TRACING_ENABLED', 'false')
    monkeypatch.setenv('LITELLM_LOCAL_MODEL_COST_MAP', 'true')
    attempts = []

    def deny_network(*args, **kwargs):
        attempts.append('network connection')
        raise AssertionError('SDK compatibility tests must not contact any service')

    monkeypatch.setattr(socket.socket, 'connect', deny_network)
    monkeypatch.setattr(socket, 'create_connection', deny_network)
    from crewai import Agent, Crew, Task, LLM
    from crewai.llms.base_llm import BaseLLM
    from crewai.tools import tool

    class OfflineLLM(BaseLLM):
        def __init__(self):
            super().__init__(model='offline-test', temperature=0)
            self.calls = 0

        def call(self, messages, tools=None, callbacks=None, available_functions=None, **kwargs):
            self.calls += 1
            return 'Final Answer: Offline compatibility check complete.'

        def supports_function_calling(self):
            return False

    yield Agent, Crew, Task, LLM, tool, OfflineLLM()
    assert not attempts


def test_production_crew_factory_builds_with_real_sdk(offline_sdk):
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == '_setup_crewai_tools')
    namespace = {}
    exec(compile(ast.Module(body=[factory], type_ignores=[]), 'main.py', 'exec'), namespace)
    crew = namespace['_setup_crewai_tools'](*offline_sdk)
    assert len(crew.agents) == 2
    assert len(crew.tasks) == 2
    assert [len(agent.tools) for agent in crew.agents] == [2, 1]
    assert crew.tasks[1].context == [crew.tasks[0]]
    assert offline_sdk[-1].calls == 0


def test_real_agent_task_and_crew_kickoff_use_only_offline_llm(offline_sdk):
    Agent, Crew, Task, _, _, llm = offline_sdk
    agent = Agent(role='Offline check', goal='Return the offline answer',
                  backstory='Test only.', llm=llm, verbose=False)
    task = Task(description='Return the offline answer',
                expected_output='Offline compatibility check complete.', agent=agent)
    result = Crew(agents=[agent], tasks=[task], verbose=False, tracing=False).kickoff()
    assert 'Offline compatibility check complete.' in str(result)
    assert llm.calls >= 1


def test_installed_crewai_metadata_accepts_patched_mcp():
    mcp_dependency = next(Requirement(line) for line in requires('crewai')
                          if Requirement(line).name == 'mcp')
    installed = version('mcp')
    assert Version(installed) >= Version('1.30.0')
    assert mcp_dependency.specifier.contains(installed)


def test_mcp_advisory_is_fixed_by_pin_not_suppressed_in_baseline():
    direct = [Requirement(line.split('#', 1)[0].strip())
              for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
              if line.split('#', 1)[0].strip()]
    mcp = next(req for req in direct if req.name == 'mcp')
    assert mcp.specifier.contains('1.30.0')
    assert not mcp.specifier.contains('1.29.1')
    baseline = (ROOT / 'deploy/audit-baseline.txt').read_text(encoding='utf-8')
    assert not any(line.startswith('mcp==') for line in baseline.splitlines())
    assert 'CVE-2026-59951' not in baseline
    assert 'GHSA-84m7-p3x7-pcfv' not in baseline


@pytest.mark.parametrize('model', [
    'gemini/gemini-2.5-flash',
    'mistral/mistral-medium-latest',
    'groq/llama-3.3-70b-versatile',
])
def test_configured_provider_adapters_construct_without_network(offline_sdk, model):
    llm = offline_sdk[3](model=model, api_key='offline-test-only', temperature=0)
    assert llm is not None
