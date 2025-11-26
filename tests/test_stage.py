from typing import List, Tuple
from unittest.mock import patch

import pytest
from visionapi.sae_pb2 import Detection, SaeMessage
from visionapi.common_pb2 import MessageType

from geomapper.config import (CameraCopyConfig, CameraGeomappingConfig,
                              GeoMapperConfig, RedisConfig)
from geomapper.stage import run_stage

@pytest.fixture(autouse=True)
def disable_prometheus():
    with patch('geomapper.stage.start_http_server'):
        yield

@pytest.fixture
def set_cameras_config():
    with patch('geomapper.stage.GeoMapperConfig') as mock_config:
        def _make_mock_config(cameras):
            mock_config.return_value = GeoMapperConfig(
                log_level='WARNING',
                cameras=cameras,
                redis=RedisConfig(
                    output_stream_prefix='output_prefix',
                )
            )
        yield _make_mock_config

@pytest.fixture
def redis_publisher_mock():
    with patch('geomapper.stage.RedisPublisher') as mock_publisher:
        yield mock_publisher.return_value

@pytest.fixture
def inject_consumer_messages():
    with patch('geomapper.stage.RedisConsumer') as mock_consumer:
        def _inject_messages(messages):
            mock_consumer.return_value.return_value.__iter__.return_value = iter(messages)
        yield _inject_messages


def test_missing_location(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([CameraCopyConfig(stream_id='stream1')])
    
    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1, 
                                                      source_id='stream1',
                                                      location=None)),
    ])

    run_stage()

    # Assert that no message is emitted since camera location is missing
    assert redis_publisher_mock.call_count == 0

def test_mismatched_source_id(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([CameraCopyConfig(stream_id='stream1')])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1, 
                                                      source_id='unknown_stream',
                                                      location=(10.0, 20.0))),
    ])

    run_stage()

    # Assert that no message is emitted since source_id does not match any configured camera
    assert redis_publisher_mock.call_count == 0

def test_copy_mode(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([CameraCopyConfig(stream_id='stream1')])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1, 
                                                      source_id='stream1',
                                                      location=(10.0, 20.0), 
                                                      detections=[
                                                          _make_detection((0.5, 0.5), 1),
                                                          _make_detection((0.6, 0.6), 2),
                                                      ])),
    ])

    run_stage()

    # Assert that the message is output onto the correct stream
    assert redis_publisher_mock.call_count == 1
    assert redis_publisher_mock.call_args_list[0].args[0] == 'output_prefix:stream1'

    # Assert that the mapping was done correctly (i.e. location copied to all detections)
    msg = SaeMessage()
    msg.ParseFromString(redis_publisher_mock.call_args_list[0].args[1])
    assert msg.frame.timestamp_utc_ms == 1
    assert msg.frame.camera_location.latitude == 10.0
    assert msg.frame.camera_location.longitude == 20.0
    for detection in msg.detections:
        assert detection.geo_coordinate.latitude == 10.0
        assert detection.geo_coordinate.longitude == 20.0

def test_map_mode_no_location(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([CameraGeomappingConfig(
        stream_id='stream1',
        heading_deg=90.0,
        image_width_px=1920,
        image_height_px=1080,
        view_x_deg=60.0,
    )])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1, 
                                                      source_id='stream1',
                                                      location=None,
                                                      detections=[
                                                          _make_detection((0.5, 0.5), 1),
                                                      ])),
    ])

    run_stage()

    # Assert that no message is emitted since camera location is missing
    assert redis_publisher_mock.call_count == 0

def test_map_mode_with_location(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([CameraGeomappingConfig(
        stream_id='stream1',
        heading_deg=135.0,
        image_width_px=1920,
        image_height_px=1080,
        view_x_deg=60.0,
        tilt_deg=45.0,
        elevation_m=10.0,
    )])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1, 
                                                      source_id='stream1',
                                                      location=(10.0, 20.0),
                                                      detections=[
                                                          _make_detection((0.5, 0.5), 1),  # center of image
                                                      ])),
    ])

    run_stage()

    # Assert that the message is output onto the correct stream
    assert redis_publisher_mock.call_count == 1
    assert redis_publisher_mock.call_args_list[0].args[0] == 'output_prefix:stream1'

    # Assert that the mapping was done (approximate check)
    msg = SaeMessage()
    msg.ParseFromString(redis_publisher_mock.call_args_list[0].args[1])
    assert msg.frame.timestamp_utc_ms == 1
    assert msg.frame.camera_location.latitude == 10.0
    assert msg.frame.camera_location.longitude == 20.0
    for detection in msg.detections:
        # Since the detection is at the center of the image, it should map close to the camera location but offset slightly
        assert 0.00001 < abs(detection.geo_coordinate.latitude - 10.0) < 0.01
        assert 0.00001 < abs(detection.geo_coordinate.longitude - 20.0) < 0.01

def _make_sae_msg_bytes(timestamp: int, source_id: str, location: Tuple[float, float] = None, detections: List[Detection] = None) -> bytes:
    sae_msg = SaeMessage()
    sae_msg.frame.timestamp_utc_ms = timestamp
    sae_msg.frame.shape.width = 1920
    sae_msg.frame.shape.height = 1080
    sae_msg.frame.shape.channels = 3
    sae_msg.frame.source_id = source_id
    if location is not None:
        sae_msg.frame.camera_location.latitude = location[0]
        sae_msg.frame.camera_location.longitude = location[1]
    if detections is not None:
        sae_msg.detections.extend(detections)
    sae_msg.type = MessageType.SAE
    return sae_msg.SerializeToString()

def _make_detection(center_xy: Tuple[float], class_id: int) -> Detection:
    detection = Detection()
    detection.bounding_box.min_x=center_xy[0]
    detection.bounding_box.min_y=center_xy[1]
    detection.bounding_box.max_x=center_xy[0]
    detection.bounding_box.max_y=center_xy[1]
    detection.confidence=0.9
    detection.class_id=class_id
    return detection