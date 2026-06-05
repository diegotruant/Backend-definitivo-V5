import 'package:in_person_test_tablet/domain/entities/connected_device.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';

/// Contratto hub BLE: scansione, connessione multi-dispositivo, stream metriche.
abstract class BleHubRepository {
  /// Dispositivi trovati in scansione (aggiornamento continuo).
  Stream<List<DiscoveredDevice>> watchDiscoveredDevices();

  /// Dispositivi attualmente gestiti (connessi o in connessione).
  Stream<List<ConnectedDevice>> watchConnectedDevices();

  /// Metriche live fuse da rullo + wearables.
  Stream<PhysiologicalSnapshot> watchLiveSnapshot();

  /// true se il Bluetooth dell'host è disponibile e autorizzato.
  Future<bool> ensureReady();

  Future<void> startScan({Set<DeviceKind>? kinds});

  Future<void> stopScan();

  Future<void> connect(DiscoveredDevice device);

  Future<void> disconnect(String deviceId);

  Future<void> dispose();
}
