from typing import Literal

from pydantic import BaseModel, Field

from .bmi_formulation import BMICxx


class SFTParams(BaseModel):
    """Class for validating SFT Parameters"""

    pass


class SFT(BMICxx):
    """A BMIC++ implementation for SFT module"""

    model_params: SFTParams = None
    registration_function: str = "none"
    main_output_variable: str = "num_cells"
    model_name: Literal["SFT"] = Field("SFT", alias="model_type_name")

    _variable_names_map = {"ground_temperature": "TG"}
