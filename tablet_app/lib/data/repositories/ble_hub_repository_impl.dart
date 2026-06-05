import 'package:in_person_test_tablet/core/config/app_config.dart';
import 'package:in_person_test_tablet/data/ble/fake_ble_hub.dart';
import 'package:in_person_test_tablet/data/ble/flutter_ble_hub.dart';
import 'package:in_person_test_tablet/domain/entities/connected_device.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';
import 'package:in_person_test_tablet/domain/repositories/ble_hub_repository.dart';

/// Factory che sceglie hub reale o simulato in base a [AppConfig].
class BleHubRepositoryImpl implements BleHubRepository {
  BleHubRepositoryImpl({AppConfig? config})
      : _delegate = (config ?? AppConfig.current).useFakeBle
            ? FakeBleHub()
            : FlutterBleHub();

  final BleHubRepository _delegate;

  @override
  Future<bool> ensureReady() => _delegate.ensureReady();

  @override
  Stream<List<ConnectedDevice>> watchConnectedDevices() =>
      _delegate.watchConnectedDevices();

  @override
  Stream<List<DiscoveredDevice>> watchDiscoveredDevices() =>
      _delegate.watchDiscoveredDevices();

  @override
  Stream<PhysiologicalSnapshot> watchLiveSnapshot() =>
      _delegate.watchLiveSnapshot();

  @override
  Future<void> connect(DiscoveredDevice device) => _delegate.connect(device);

  @override
  Future<void> disconnect(String deviceId) => _delegate.disconnect(deviceId);

  @override
  Future<void> dispose() => _delegate.dispose();

  @override
  Future<void> startScan({Set<DeviceKind>? kinds}) =>
      _delegate.startScan(kinds: kinds);

  @override
  Future<void> stopScan() => _delegate.stopScan();
}
