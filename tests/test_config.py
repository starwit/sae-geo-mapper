import pytest
from pydantic import ValidationError

from geomapper.config import (CameraCopyConfig, CameraGeomappingConfig,
                              GeoMapperConfig)


def test_empty_cameras():
    with pytest.raises(ValidationError):
        GeoMapperConfig(
            cameras=[]
        )

def test_copy_camera_dict():
    config = GeoMapperConfig(
        cameras=[{
            'mode': 'copy',
            'stream_id': 'stream1',
        }]
    )

    assert isinstance(config.cameras[0], CameraCopyConfig)

def test_copy_camera_constructor():
    config = GeoMapperConfig(
        cameras=[CameraCopyConfig(stream_id='stream')]
    )

    assert isinstance(config.cameras[0], CameraCopyConfig)

def test_mapping_camera_dict():
    config = GeoMapperConfig(
        cameras=[{
            'mode': 'map',
            'stream_id': 'stream1',
            'heading_deg': 180,
        }]
    )

    assert isinstance(config.cameras[0], CameraGeomappingConfig)
    assert config.cameras[0].heading_deg == 180

def test_mapping_camera_constructor():
    config = GeoMapperConfig(
        cameras=[CameraGeomappingConfig(
            stream_id='stream1',
            heading_deg=180,
        )]
    )

    assert isinstance(config.cameras[0], CameraGeomappingConfig)
    assert config.cameras[0].heading_deg == 180