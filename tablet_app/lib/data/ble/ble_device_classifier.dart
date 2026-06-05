import 'package:in_person_test_tablet/data/ble/ble_gatt_profiles.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';

/// Classifica un dispositivo BLE in base ai servizi GATT annunciati.
class BleDeviceClassifier {
  const BleDeviceClassifier();

  DeviceKind? classifyFromServiceUuids(List<String> serviceUuids) {
    final normalized = serviceUuids
        .map((u) => u.toLowerCase().replaceAll('-', ''))
        .toSet();

    bool has(String uuid) =>
        normalized.contains(uuid.replaceAll('-', '').toLowerCase());

    if (has(BleGattProfiles.fitnessMachineService) ||
        has(BleGattProfiles.cyclingPowerService)) {
      return DeviceKind.roller;
    }
    if (has(BleGattProfiles.heartRateService)) {
      return DeviceKind.heartRate;
    }
    return null;
  }

  /// Euristica sul nome commerciale (fallback se i servizi non sono in adv).
  DeviceKind? classifyFromName(String name) {
    final n = name.toLowerCase();
    if (n.contains('kickr') ||
        n.contains('neo') ||
        n.contains('tacx') ||
        n.contains('wahoo') ||
        n.contains('elite') ||
        n.contains('roller') ||
        n.contains('rullo')) {
      return DeviceKind.roller;
    }
    if (n.contains('hrm') ||
        n.contains('polar') ||
        n.contains('garmin') ||
        n.contains('h10') ||
        n.contains('heart')) {
      return DeviceKind.heartRate;
    }
    if (n.contains('core') || n.contains('body temp') || n.contains('temp')) {
      return DeviceKind.coreTemperature;
    }
    return null;
  }
}
