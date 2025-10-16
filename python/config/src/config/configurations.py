from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Union, Dict, Any

from pydantic import BaseModel, ConfigDict, DirectoryPath, Field, FilePath, conint, field_serializer

PosInt = conint(gt=0)


class Forcing(BaseModel):
    """Model for ngen forcing component inputs"""

    model_config = ConfigDict()

    class Provider(str, Enum):
        """Enumeration of the supported NGEN forcing provider strings"""

        CSV = "CsvPerFeature"
        NetCDF = "NetCDF"
        Lumped = "ForcingsEngineLumpedDataProvider"

    # required
    file_pattern: Optional[Union[FilePath, str]] = None
    path: Union[DirectoryPath, FilePath]
    provider: Provider = Field(Provider.CSV)
    params: Optional[Dict[str, Any]] = None

    def resolve_paths(self):
        if isinstance(self.file_pattern, Path):
            self.file_pattern = self.file_pattern.resolve()
        self.path = self.path.resolve()
        if self.params:
            for k, v in self.params.items():
                if isinstance(v, str) and Path(v).exists():
                    self.params[k] = Path(v).resolve()


class Time(BaseModel):
    """Model for ngen time configuraiton components"""

    # required
    start_time: datetime
    end_time: datetime
    # reasonable default (defacto, actually???)
    output_interval: PosInt = 3600

    # FIXME https://github.com/samuelcolvin/pydantic/issues/2277
    # Until 1.10, it looks like nested encoder config doesn't apply
    # so you have to define the encoder at the top level object that
    # will be serialized...
    class Config:
        # override how datetime format looks in .json()
        # json_encoders = {datetime: lambda v: v.strftime("%Y-%m-%d %H:%M:%S")}
        @field_serializer("timestamp")
        def serialize_dt(self, dt: datetime) -> str:
            return dt.strftime("%Y-%m-%d %H:%M:%S")


class Routing(BaseModel):
    """Model for ngen routing configuration information"""

    # required
    config: FilePath = Field(alias="t_route_config_file_with_path")
    # optional/not used TODO make default None?
    path: Optional[str] = Field("", alias="t_route_connection_path")  # TODO deprecate this field?

    def resolve_paths(self):
        self.config = self.config.resolve()

    def dict(self, **kwargs):
        # Can override the `dict` call so we ALWAYS `use_aliases` when this model
        # is serialized
        kwargs.setdefault("by_alias", True)
        return super().dict(**kwargs)
