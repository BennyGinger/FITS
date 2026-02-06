from dataclasses import dataclass


@dataclass(frozen=True)
class StepProfile:
    distribution: str
    step_name: str
    
    def dump(self) -> dict[str, str]:
        """Return a dictionary representation of the StepProfile for provenance tracking."""
        return {
            "distribution": self.distribution,
            "step_name": self.step_name,
        }