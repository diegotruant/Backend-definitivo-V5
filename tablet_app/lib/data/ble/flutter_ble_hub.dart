import 'dart:async';

import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:in_person_test_tablet/data/ble/ble_device_classifier.dart';
import 'package:in_person_test_tablet/domain/entities/ble_connection_status.dart';
import 'package:in_person_test_tablet/domain/entities/connected_device.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';
import 'package:in_person_test_tablet/domain/repositories/ble_hub_repository.dart';

/// Implementazione reale BLE (flutter_blue_plus).
///
/// Fase 1: scansione + connessione base. Parsing GATT per metriche
/// verrà aggiunto negli adapter dedicati (prossimo step).
class FlutterBleHub implements BleHubRepository {
  FlutterBleHub({BleDeviceClassifier? classifier})
      : _classifier = classifier ?? const BleDeviceClassifier();

  final BleDeviceClassifier _classifier;
  final _discovered = StreamController<List<DiscoveredDevice>>.broadcast();
  final _connected = StreamController<List<ConnectedDevice>>.broadcast();
  final _snapshot = StreamController<PhysiologicalSnapshot>.broadcast();

  final Map<String, ConnectedDevice> _connections = {};
  final Map<String, DiscoveredDevice> _seen = {};
  StreamSubscription<List<ScanResult>>? _scanSub;

  @override
  Future<bool> ensureReady() async {
    if (await FlutterBluePlus.isSupported == false) return false;
    final state = await FlutterBluePlus.adapterState.first;
    if (state != BluetoothAdapterState.on) {
      // Su Android/iOS l'utente deve attivare BT dalle impostazioni.
      return false;
    }
    return true;
  }

  @override
  Stream<List<DiscoveredDevice>> watchDiscoveredDevices() =>
      _discovered.stream;

  @override
  Stream<List<ConnectedDevice>> watchConnectedDevices() => _connected.stream;

  @override
  Stream<PhysiologicalSnapshot> watchLiveSnapshot() => _snapshot.stream;

  @override
  Future<void> startScan({Set<DeviceKind>? kinds}) async {
    await stopScan();
    _seen.clear();
    await FlutterBluePlus.startScan(timeout: const Duration(seconds: 15));

    _scanSub = FlutterBluePlus.scanResults.listen((results) {
      for (final r in results) {
        final id = r.device.remoteId.str;
        final name = r.device.platformName.isNotEmpty
            ? r.device.platformName
            : r.device.advName;

        final serviceUuids =
            r.advertisementData.serviceUuids.map((g) => g.str).toList();
        var kind = _classifier.classifyFromServiceUuids(serviceUuids) ??
            _classifier.classifyFromName(name);
        kind ??= DeviceKind.roller; // default provvisorio se sconosciuto

        if (kinds != null && !kinds.contains(kind)) continue;

        _seen[id] = DiscoveredDevice(
          id: id,
          name: name.isEmpty ? 'Dispositivo $id' : name,
          kind: kind,
          rssi: r.rssi,
        );
      }
      _discovered.add(_seen.values.toList(growable: false));
    });
  }

  @override
  Future<void> stopScan() async {
    await _scanSub?.cancel();
    _scanSub = null;
    await FlutterBluePlus.stopScan();
  }

  @override
  Future<void> connect(DiscoveredDevice device) async {
    _connections[device.id] = ConnectedDevice(
      id: device.id,
      name: device.name,
      kind: device.kind,
      status: BleConnectionStatus.connecting,
    );
    _emitConnected();

    try {
      final ble = BluetoothDevice.fromId(device.id);
      await ble.connect(autoConnect: false);
      _connections[device.id] = ConnectedDevice(
        id: device.id,
        name: device.name,
        kind: device.kind,
        status: BleConnectionStatus.connected,
      );
      // TODO: registrare BleDeviceAdapter per parsing GATT
    } catch (e) {
      _connections[device.id] = ConnectedDevice(
        id: device.id,
        name: device.name,
        kind: device.kind,
        status: BleConnectionStatus.error,
        lastError: e.toString(),
      );
    }
    _emitConnected();
  }

  @override
  Future<void> disconnect(String deviceId) async {
    try {
      await BluetoothDevice.fromId(deviceId).disconnect();
    } catch (_) {}
    _connections.remove(deviceId);
    _emitConnected();
  }

  void _emitConnected() =>
      _connected.add(_connections.values.toList(growable: false));

  @override
  Future<void> dispose() async {
    await stopScan();
    for (final id in _connections.keys.toList()) {
      await disconnect(id);
    }
    await _discovered.close();
    await _connected.close();
    await _snapshot.close();
  }
}
