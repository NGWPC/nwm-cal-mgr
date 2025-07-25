from typing import Literal

from pydantic import Field

from .bmi_formulation import BMICxx


class SMP(BMICxx):
    """A BMIC++ implementation for SMP module"""

    registration_function: str = "none"
    main_output_variable: str = "soil_water_table"
    model_name: Literal["SMP"] = Field("SMP", alias="model_type_name")

    _variable_names_map = {"soil_storage": "SOIL_STORAGE", "soil_storage_change": "SOIL_STORAGE_CHANGE"}
