from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StepProfile:
    distribution: str
    step_name: str
    
    def dump(self) -> dict[str, str]:
        """
        Return a dictionary representation of the StepProfile for provenance tracking.
        """
        return {"distribution": self.distribution,
                "step_name": self.step_name,}

def provenance_payload(step_profile: StepProfile, **kwargs) -> dict[str, Any]:
    """
    Builds payloads for FITS workflow steps, ensuring consistent provenance information. Any other keyword arguments can be included as needed for specific steps, which will then be included in the provenance info.
    """
    provenance_info: dict[str, Any] = step_profile.dump()
    provenance_info.update(**kwargs)
    return provenance_info