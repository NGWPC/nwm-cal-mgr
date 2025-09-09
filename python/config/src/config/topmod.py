from typing import ClassVar, Literal, Mapping, Optional

from pydantic import BaseModel, Field

from .bmi_formulation import BMIC


class TopmodParams(BaseModel):
    """Class for validating Topmod Parameters"""

    sr0: Optional[float] = None
    srmax: Optional[float] = None
    szm: Optional[float] = None
    t0: Optional[float] = None
    td: Optional[float] = None


class Topmod(BMIC):
    """A BMIC implementation for the Topmod ngen module"""

    model_params: Optional[TopmodParams] = None
    main_output_variable: str = "Qout"
    registration_function: str = "register_bmi_topmodel"
    # NOTE aliases don't propagate to subclasses, so we have to repeat the alias
    model_name: Literal["TOPMODEL"] = Field(default="TOPMODEL", alias="model_type_name")

    # can set some default name map entries...will be overridden at construction
    # if a name_map with the same key is passed in, otherwise the name_map
    # will also include these mappings
    variable_names_map: ClassVar[Mapping[str, str]] = {
        # "water_potential_evaporation_flux": "EVAPOTRANS",
        "atmosphere_water__liquid_equivalent_precipitation_rate": "QINSUR"
    }
