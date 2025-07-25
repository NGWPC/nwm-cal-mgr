from typing import Literal

from pydantic import BaseModel, Field

from .bmi_formulation import BMICxx


class LASAMParams(BaseModel):
    """Class for validating LASAM Parameters"""

    pass


class LASAM(BMICxx):
    """A BMIC++ implementation for LASAM module"""

    model_params: LASAMParams = None
    registration_function: str = "none"
    main_output_variable: str = "precipitation_rate"
    model_name: Literal["LASAM"] = Field("LASAM", alias="model_type_name")

    _variable_names_map = {"precipitation_rate": "QINSUR", "potential_evapotranspiration_rate": "EVAPOTRANS"}
