from pydantic import ValidationError
import pytest
from geomapper.config import GeoMapperConfig

def test_empty_cameras():
    with pytest.raises(ValidationError):
        GeoMapperConfig(
            cameras=[]
        )

def test_copy_camera():
    GeoMapperConfig(
        cameras=[{
            'mode': 'copy',
            'stream_id': 'stream1',
        }]
    )

def test_mapping_camera():
    GeoMapperConfig(
        cameras=[{
            'mode': 'map',
            'stream_id': 'stream1',
            'heading_deg': 180,
        }]
    )