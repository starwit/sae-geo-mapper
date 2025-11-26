from unittest.mock import patch

from visionapi.sae_pb2 import Detection, SaeMessage

# from geomapper.config import GeoMapperConfig, RedisConfig
# from geomapper.stage import run_stage

# Use cases

## Frame cam location set => map detections
## Frame cam location set, no mapping parameters => copy location to all detection
## Frame cam location not set => discard and log warning






@patch('geomapper.stage.GeoMapperConfig')
@patch('geomapper.stage.RedisConsumer')
@patch('geomapper.stage.RedisPublisher')
def not_test_smoke(mock_redis_publisher, mock_redis_consumer, mock_config):
    mock_config.return_value = GeoMapperConfig(
        log_level='WARNING',
        cameras=[MappingCameraConfig(
            stream_id='stream1',

        )],
        redis=RedisConfig(
            input_stream_prefix='input_prefix',
            output_stream_prefix='output_prefix',
        )
    )

    publisher_mock = mock_redis_publisher.return_value 
    
    # Mock three messages for the component to read from redis
    mock_redis_consumer.return_value.return_value.__iter__.return_value = iter([
        ('videosource:stream1', _make_sae_msg_bytes(1)),
        ('videosource:stream1', _make_sae_msg_bytes(2)),
        ('videosource:stream1', _make_sae_msg_bytes(3)),
    ])

    run_stage()

    # Assert that exactly one message is emitted onto the correct stream
    assert len(publisher_mock.mock_calls) == 1
    assert publisher_mock.call_args_list[0].args[0] == 'output_prefix:stream1'

    # Assert that the mapping was done correctly
    msg = SaeMessage()
    msg.ParseFromString(publisher_mock.call_args_list[0].args[1])
    assert msg.frame.timestamp_utc_ms == 3


def _make_sae_msg_bytes(timestamp: int):
    sae_msg = SaeMessage()
    sae_msg.frame.timestamp_utc_ms = timestamp
    sae_msg.frame.shape.width = 5
    sae_msg.frame.shape.height = 5
    sae_msg.frame.shape.channels = 1
    sae_msg.frame.frame_data = b'\x00' * (5 * 5 * 1)  # Dummy data
    sae_msg.frame.camera_location.latitude = 20
    sae_msg.frame.camera_location.longitude = 10
    return sae_msg.SerializeToString()

def _make_detection(center_y: float, class_id: int) -> Detection:
    detection = Detection()
    detection.bounding_box.min_x=0.1
    detection.bounding_box.min_y=max(center_y - 0.1, 0)
    detection.bounding_box.max_x=0.2
    detection.bounding_box.max_y=min(center_y + 0.1, 1)
    detection.confidence=0.9
    detection.class_id=class_id
    return detection