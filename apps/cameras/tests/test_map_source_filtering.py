from apps.cameras.models import Go2RTCInstance, SourceType
from apps.cameras.services import get_camera_map_markers


def test_source_filter_excludes_go2rtc_markers_for_non_go2rtc_sources(db) -> None:
    Go2RTCInstance.objects.create(
        name="go2rtc-instance",
        host="example.local",
        port=1984,
        geo_country="Croatia",
        geo_city="Zagreb",
        geo_latitude=45.8150,
        geo_longitude=15.9780,
        last_sync_status=Go2RTCInstance.LastSyncStatus.SUCCESS,
    )

    payload = get_camera_map_markers(source_type=SourceType.WINDY, include_go2rtc_instances=True)

    assert all(marker.get("marker_kind") != "go2rtc_instance" for marker in payload.get("markers", []))
