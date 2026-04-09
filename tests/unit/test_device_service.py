from wecom_automation.core.models import DeviceInfo
from wecom_automation.services.device_service import DeviceDiscoveryService


def test_parse_device_line_with_full_metadata():
    line = "R58M35XXXX device product:dreamltexx model:SM_G950F device:dreamlte transport_id:2 usb:1-1 features:abc"
    info = DeviceDiscoveryService._parse_device_line(line)
    assert info is not None
    assert info.serial == "R58M35XXXX"
    assert info.state == "device"
    assert info.product == "dreamltexx"
    assert info.model == "SM_G950F"
    assert info.device == "dreamlte"
    assert info.transport_id == 2
    assert info.usb == "1-1"
    assert info.features == "abc"


def test_parse_device_line_handles_minimal_input():
    line = "emulator-5554 offline"
    info = DeviceDiscoveryService._parse_device_line(line)
    assert info is not None
    assert info.serial == "emulator-5554"
    assert info.state == "offline"
    assert info.product is None


def test_parse_getprop_output_extracts_values():
    raw = """
[ro.product.manufacturer]: [Google]
[ro.product.model]: [Pixel 8]
[ro.build.version.release]: [14]
[ro.build.version.sdk]: [34]
    """.strip()

    props = DeviceDiscoveryService._parse_getprop_output(raw)
    assert props["ro.product.manufacturer"] == "Google"
    assert props["ro.product.model"] == "Pixel 8"
    assert props["ro.build.version.sdk"] == "34"


def test_apply_properties_prefers_existing_model():
    service = DeviceDiscoveryService()
    device = DeviceInfo(serial="abc123", state="device", model="CustomModel")
    props = {
        "ro.product.manufacturer": "Google",
        "ro.product.model": "Pixel 8",
        "ro.build.version.sdk": "34",
        "ro.product.cpu.abi": "arm64-v8a",
        "ro.boot.serialno": "abc123",
    }

    service._apply_properties(device, props)

    # Existing model should remain untouched
    assert device.model == "CustomModel"
    # New fields should be populated
    assert device.manufacturer == "Google"
    assert device.sdk_version == "34"
    assert device.abi == "arm64-v8a"
    assert device.extra_props["ro.boot.serialno"] == "abc123"


def test_device_info_to_dict_includes_runtime_fields():
    device = DeviceInfo(
        serial="xyz",
        state="device",
        screen_resolution="1080x2400",
        battery_level="90%",
        usb_debugging=True,
        internal_storage="20G available of 64G",
    )
    data = device.to_dict()
    assert data["screen_resolution"] == "1080x2400"
    assert data["battery_level"] == "90%"
    assert data["usb_debugging"] is True
    assert data["internal_storage"] == "20G available of 64G"
