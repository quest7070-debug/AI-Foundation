from dataclasses import dataclass
from typing import Protocol
from .agent_tools import CapabilityAgentTools

class TestPort(Protocol):
    def run_tests(self, target: str) -> str: ...

@dataclass(frozen=True)
class CodingResult:
    observed: str
    test_result: str
    write_result: str | None = None
    verified: bool = False

@dataclass
class CodingSpecialist:
    tools: CapabilityAgentTools
    tests: TestPort
    protected: object | None = None
    acceptance_target: str = ''  # host-bound, never selected by the model

    def inspect(self, target: str) -> CodingResult:
        return CodingResult(self.tools.read(target), "NOT_RUN: observational inspect", verified=True)

    def apply_verified_change(self, target: str, content: str) -> CodingResult:
        # Scope authority stays in CapabilityAgentTools. ProtectedResources is a
        # distinct host policy, so validate the normalized target before the Guarded
        # write without moving write/effect authority back into the specialist.
        before=self.tools.read(target)
        test_target=self.acceptance_target or target
        try:
            test_before=self.tests.run_tests(test_target)
        except RuntimeError as e:
            # A failing baseline is often exactly what a code repair must fix.
            test_before='FAILED: '+str(e)
        if self.protected is not None:
            safe_target=self.tools.write_capability.authorize_target(target)
            self.protected.validate_write(safe_target)
        write=self.tools.write(target,content)
        if write != "VERIFIED_COMPLETE":
            return CodingResult(
                before,
                f'before={test_before}; after=NOT_RUN: effect={write}',
                write,
            )
        try:
            test_after=self.tests.run_tests(test_target)
        except RuntimeError as e:
            return CodingResult(
                before,
                f'before={test_before}; after=FAILED: {e}',
                write,
            )
        return CodingResult(before, f'before={test_before}; after={test_after}', write, True)

    def develop(self, *, agent, instruction: str, target: str, acceptance_target: str,
                max_repairs: int = 1, publish_draft=None,
                repair_agent=None, review_agent=None):
        """Run bounded edit/test/repair through this existing guarded specialist."""
        from .development_loop import run_development_loop
        return run_development_loop(
            specialist=self, agent=agent, instruction=instruction, target=target,
            acceptance_target=acceptance_target, max_repairs=max_repairs,
            publish_draft=publish_draft, repair_agent=repair_agent,
            review_agent=review_agent,
        )

