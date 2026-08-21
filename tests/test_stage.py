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
        yield mock_publisher.return_value.__enter__.return_value

@pytest.fixture
def inject_consumer_messages():
    with patch('geomapper.stage.RedisConsumer') as mock_consumer:
        def _inject_messages(messages):
            mock_consumer.return_value.__enter__.return_value.return_value.__iter__.return_value = iter(messages)
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
                                                          _make_detection((0.5, 0.5, 0.5, 0.5), 1),
                                                          _make_detection((0.6, 0.6, 0.6, 0.6), 2),
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
                                                          _make_detection((0.5, 0.5, 0.5, 0.5), 1),
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
                                                          _make_detection((0.5, 0.5, 0.5, 0.5), 1),  # center of image
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
        # Since the detection is at the center of the image, it should map close to the camera location but offset slightly to the southeast
        assert 0.00001 < (10.0 - detection.geo_coordinate.latitude) < 0.01
        assert 0.00001 < (detection.geo_coordinate.longitude - 20.0) < 0.01

def test_map_mode_edge_detections_mapped_by_default(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([_make_geomapping_config()])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1,
                                                      source_id='stream1',
                                                      location=(10.0, 20.0),
                                                      detections=[
                                                          _make_detection((0.005, 0.4, 0.3, 0.6), 1),  # close to the left image border
                                                      ])),
    ])

    run_stage()

    # Assert that the edge detection is mapped as usual (ignore_edge_detections defaults to false)
    msg = SaeMessage()
    msg.ParseFromString(redis_publisher_mock.call_args_list[0].args[1])
    assert len(msg.detections) == 1
    assert msg.detections[0].HasField('geo_coordinate')

def test_map_mode_ignore_edge_detections(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([_make_geomapping_config(ignore_edge_detections=True)])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1,
                                                      source_id='stream1',
                                                      location=(10.0, 20.0),
                                                      detections=[
                                                          _make_detection((0.4, 0.4, 0.6, 0.6), 1),      # well within the image
                                                          _make_detection((0.02, 0.4, 0.3, 0.6), 2),     # close to the left image border, but still outside the tolerance band
                                                          _make_detection((0.005, 0.4, 0.3, 0.6), 3),    # left image border, detected slightly inset
                                                          _make_detection((0.4, 0.7, 0.6, 0.995), 4),    # bottom image border, detected slightly inset
                                                          _make_detection((0.0, 0.4, 0.2, 0.6), 5),      # exactly on the left image border
                                                      ])),
    ])

    run_stage()

    # Assert that all detections are retained, but only the ones outside the tolerance band around the image border have been mapped
    msg = SaeMessage()
    msg.ParseFromString(redis_publisher_mock.call_args_list[0].args[1])
    assert len(msg.detections) == 5
    assert msg.detections[0].HasField('geo_coordinate')
    assert msg.detections[1].HasField('geo_coordinate')
    assert not msg.detections[2].HasField('geo_coordinate')
    assert not msg.detections[3].HasField('geo_coordinate')
    assert not msg.detections[4].HasField('geo_coordinate')

def test_map_mode_ignore_edge_detections_with_removal(redis_publisher_mock, inject_consumer_messages, set_cameras_config):
    set_cameras_config([_make_geomapping_config(ignore_edge_detections=True, remove_unmapped_detections=True)])

    inject_consumer_messages([
        ('objecttracker:stream1', _make_sae_msg_bytes(timestamp=1,
                                                      source_id='stream1',
                                                      location=(10.0, 20.0),
                                                      detections=[
                                                          _make_detection((0.4, 0.4, 0.6, 0.6), 1),    # well within the image
                                                          _make_detection((0.005, 0.4, 0.3, 0.6), 2),  # left image border, detected slightly inset
                                                      ])),
    ])

    run_stage()

    # Assert that the ignored edge detection has been removed from the message
    msg = SaeMessage()
    msg.ParseFromString(redis_publisher_mock.call_args_list[0].args[1])
    assert len(msg.detections) == 1
    assert msg.detections[0].class_id == 1
    assert msg.detections[0].HasField('geo_coordinate')

def _make_geomapping_config(**kwargs) -> CameraGeomappingConfig:
    return CameraGeomappingConfig(
        stream_id='stream1',
        heading_deg=135.0,
        image_width_px=1920,
        image_height_px=1080,
        view_x_deg=60.0,
        tilt_deg=45.0,
        elevation_m=10.0,
        **kwargs,
    )

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

def _make_detection(bbox: Tuple[float, float, float, float], class_id: int) -> Detection:
    '''bbox is (min_x, min_y, max_x, max_y) in normalized image coordinates'''
    detection = Detection()
    detection.bounding_box.min_x = bbox[0]
    detection.bounding_box.min_y = bbox[1]
    detection.bounding_box.max_x = bbox[2]
    detection.bounding_box.max_y = bbox[3]
    detection.confidence = 0.9
    detection.class_id = class_id
    return detection