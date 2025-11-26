import pytest
from pydantic import ValidationError

from geomapper.config import (CameraCopyConfig, CameraGeomappingConfig,
                              GeoMapperConfig)


def test_empty_cameras():
    with pytest.raises(ValidationError):
        GeoMapperConfig(
            log_level='WARNING',
            cameras=[]
        )

def test_copy_camera_dict():
    config = GeoMapperConfig(
        log_level='WARNING',
        cameras=[{
            'mode': 'copy',
            'stream_id': 'stream1',
        }]
    )

    assert isinstance(config.cameras[0], CameraCopyConfig)

def test_copy_camera_constructor():
    config = GeoMapperConfig(
        log_level='WARNING',
        cameras=[CameraCopyConfig(stream_id='stream')]
    )

    assert isinstance(config.cameras[0], CameraCopyConfig)

def test_mapping_camera_dict():
    config = GeoMapperConfig(
        log_level='WARNING',
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
        log_level='WARNING',
        cameras=[CameraGeomappingConfig(
            stream_id='stream1',
            heading_deg=180,
        )]
    )

    assert isinstance(config.cameras[0], CameraGeomappingConfig)
    assert config.cameras[0].heading_deg == 180