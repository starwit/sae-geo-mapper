import logging
from typing import Any, Dict, List, NamedTuple

import cameratransform as ct
from cameratransform.camera import Camera
from prometheus_client import Counter, Histogram, Summary
from shapely import Point as ShapelyPoint
from shapely import Polygon
from shapely.geometry import shape
from visionapi.sae_pb2 import BoundingBox, Detection, SaeMessage
from visionapi.common_pb2 import MessageType

from .config import GeoMapperConfig, CameraConfig, CameraMode

logging.basicConfig(format='%(asctime)s %(name)-15s %(levelname)-8s %(processName)-10s %(message)s')
logger = logging.getLogger(__name__)

GET_DURATION = Histogram('geo_mapper_get_duration', 'The time it takes to deserialize the proto until returning the tranformed result as a serialized proto',
                         buckets=(0.0025, 0.005, 0.0075, 0.01, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25))
TRANSFORM_DURATION = Summary('geo_mapper_transform_duration', 'How long the coordinate transformation takes')
OBJECT_COUNTER = Counter('geo_mapper_object_counter', 'How many detections have been transformed')
PROTO_SERIALIZATION_DURATION = Summary('geo_mapper_proto_serialization_duration', 'The time it takes to create a serialized output proto')
PROTO_DESERIALIZATION_DURATION = Summary('geo_mapper_proto_deserialization_duration', 'The time it takes to deserialize an input proto')

class Point(NamedTuple):
    x: float
    y: float


class GeoMapper:
    def __init__(self, config: GeoMapperConfig) -> None:
        self._config = config
        logger.setLevel(self._config.log_level.value)

        self._cameras: Dict[str, ct.Camera] = dict()
        self._cam_configs: Dict[str, CameraConfig] = dict()
        self._mapping_areas: Dict[str, Polygon] = dict()
        self._setup()

    def _setup(self):
        for cam_conf in self._config.cameras:
            self._cam_configs[cam_conf.stream_id] = cam_conf

            if cam_conf.mode == CameraMode.MAP:
                lens_correction = ct.NoDistortion()
                if cam_conf.abc_distortion_a is not None:
                    lens_correction = ct.ABCDistortion(
                        a=cam_conf.abc_distortion_a, 
                        b=cam_conf.abc_distortion_b, 
                        c=cam_conf.abc_distortion_c,
                    )
                if cam_conf.brown_distortion_k1 is not None:
                    lens_correction = ct.BrownLensDistortion(
                        k1=cam_conf.brown_distortion_k1,
                        k2=cam_conf.brown_distortion_k2,
                        k3=cam_conf.brown_distortion_k3,
                    )

                camera = ct.Camera(
                    projection=ct.RectilinearProjection(
                        focallength_mm=cam_conf.focallength_mm,
                        sensor_height_mm=cam_conf.sensor_height_mm,
                        sensor_width_mm=cam_conf.sensor_width_mm,
                        image_height_px=cam_conf.image_height_px,
                        image_width_px=cam_conf.image_width_px,
                        view_x_deg=cam_conf.view_x_deg,
                        view_y_deg=cam_conf.view_y_deg, 
                    ),
                    orientation=ct.SpatialOrientation(
                        elevation_m=cam_conf.elevation_m,
                        tilt_deg=cam_conf.tilt_deg,
                        heading_deg=cam_conf.heading_deg,
                        roll_deg=cam_conf.roll_deg,
                    ),
                    lens=lens_correction,
                )
            
                self._cameras[cam_conf.stream_id] = camera

                if cam_conf.mapping_area is not None:
                    self._mapping_areas[cam_conf.stream_id] = shape(cam_conf.mapping_area)

    def __call__(self, input_proto) -> Any:
        return self.get(input_proto)
    
    @GET_DURATION.time()
    def get(self, input_proto):
        sae_msg = self._unpack_proto(input_proto)
        if not sae_msg.type == MessageType.SAE:
            logger.warning(f'Unexpected message type {sae_msg.type}, discarding message')
            return None

        source_id = sae_msg.frame.source_id

        if not sae_msg.frame.HasField('camera_location'):
            logger.warning(f'Camera location is not set, discarding message (source_id={source_id})')
            return None

        cam_config = self._cam_configs.get(source_id, None)

        if cam_config is None:
            logger.warning(f'No config for message source_id={source_id} found, possible stream_id/source_id mismatch, discarding message')
            return None
        
        if cam_config.mode == CameraMode.COPY:
            self._transform_detections_copy(sae_msg)
        elif cam_config.mode == CameraMode.MAP:
            camera = self._cameras.get(source_id, None)
            self._transform_detections_map(sae_msg, camera)

        return self._pack_proto(sae_msg)
    
    def _transform_detections_copy(self, sae_msg: SaeMessage) -> None:
        '''Copy camera location to all detections in the message'''
        lat = sae_msg.frame.camera_location.latitude
        lon = sae_msg.frame.camera_location.longitude

        for detection in sae_msg.detections:
            detection.geo_coordinate.latitude = lat
            detection.geo_coordinate.longitude = lon
      
    def _transform_detections_map(self, sae_msg: SaeMessage, camera: Camera) -> None:
        '''Map detections into coordinate space, add coordinate to message and optionally filter detections that were not mapped'''
        # Cameras can move, so we read the location from current message
        camera.setGPSpos(sae_msg.frame.camera_location.latitude, sae_msg.frame.camera_location.longitude)
        
        stream_id = sae_msg.frame.source_id
        image_height_px = camera.parameters.parameters['image_height_px'].value
        image_width_px = camera.parameters.parameters['image_width_px'].value

        retained_detections: List[Detection] = []

        with TRANSFORM_DURATION.time():
            for detection in sae_msg.detections:
                center = self._get_center(detection.bounding_box)
                gps = camera.gpsFromImage([center.x * image_width_px, center.y * image_height_px], Z=self._config.object_center_elevation_m)
                lat, lon = gps[0], gps[1]
                if self._is_filtered(stream_id, lat, lon):
                    logger.debug(f'SKIPPED: cls {detection.class_id}, oid {detection.object_id.hex()}, lat {lat}, lon {lon}')
                    continue
                detection.geo_coordinate.latitude = lat
                detection.geo_coordinate.longitude = lon
                retained_detections.append(detection)
                logger.debug(f'cls {detection.class_id}, oid {detection.object_id.hex()}, lat {lat}, lon {lon}')
        
        if self._cam_configs[stream_id].remove_unmapped_detections:
            sae_msg.ClearField('detections')
            sae_msg.detections.extend(retained_detections)

    def _get_center(self, bbox: BoundingBox) -> Point:
        return Point(
            x=(bbox.min_x + bbox.max_x) / 2,
            y=(bbox.min_y + bbox.max_y) / 2
        )
    
    def _is_filtered(self, cam_id: str, lat: float, lon: float):
        if cam_id in self._mapping_areas:
            point = ShapelyPoint(lon, lat)
            return not self._mapping_areas[cam_id].contains(point)

    @PROTO_DESERIALIZATION_DURATION.time()
    def _unpack_proto(self, sae_message_bytes):
        sae_msg = SaeMessage()
        sae_msg.ParseFromString(sae_message_bytes)

        return sae_msg
    
    @PROTO_SERIALIZATION_DURATION.time()
    def _pack_proto(self, sae_msg: SaeMessage):
        return sae_msg.SerializeToString()