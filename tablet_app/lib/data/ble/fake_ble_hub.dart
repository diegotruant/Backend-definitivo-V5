import 'dart:async';
import 'dart:math';

import 'package:in_person_test_tablet/domain/entities/ble_connection_status.dart';
import 'package:in_person_test_tablet/domain/entities/connected_device.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/discovered_device.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';
import 'package:in_person_test_tablet/domain/repositories/ble_hub_repository.dart';

/// Hub BLE simulato per sviluppo UI e logica di sessione senza hardware.
class FakeBleHub implements BleHubRepository {
  FakeBleHub();

  final _discovered = StreamController<List<DiscoveredDevice>>.broadcast();
  final _connected = StreamController<List<ConnectedDevice>>.broadcast();
  final _snapshot = StreamController<PhysiologicalSnapshot>.broadcast();

  final List<DiscoveredDevice> _scanResults = [];
  final Map<String, ConnectedDevice> _connections = {};
  Timer? _scanTimer;
  Timer? _metricsTimer;
  final _rng = Random();

  static final _catalog = [
    ('fake-kickr-1', 'Wahoo KICKR', DeviceKind.roller, -58),
    ('fake-polar-1', 'Polar H10', DeviceKind.heartRate, -62),
    ('fake-core-1', 'CORE Sensor', DeviceKind.coreTemperature, -70),
  ];

  @override
  Future<bool> ensureReady() async => true;

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
    _scanResults.clear();
    _emitDiscovered();

    _scanTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      for (final (id, name, kind, rssi) in _catalog) {
        if (kinds != null && !kinds.contains(kind)) continue;
        if (_scanResults.any((d) => d.id == id)) continue;
        _scanResults.add(
          DiscoveredDevice(id: id, name: name, kind: kind, rssi: rssi),
        );
        _emitDiscovered();
      }
    });
  }

  @override
  Future<void> stopScan() async {
    _scanTimer?.cancel();
    _scanTimer = null;
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

    await Future<void>.delayed(const Duration(milliseconds: 800));

    _connections[device.id] = ConnectedDevice(
      id: device.id,
      name: device.name,
      kind: device.kind,
      status: BleConnectionStatus.connected,
    );
    _emitConnected();
    _startMetricsIfNeeded();
  }

  @override
  Future<void> disconnect(String deviceId) async {
    _connections.remove(deviceId);
    _emitConnected();
    if (_connections.isEmpty) {
      _metricsTimer?.cancel();
      _metricsTimer = null;
    }
  }

  void _startMetricsIfNeeded() {
    if (_metricsTimer != null) return;
    _metricsTimer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      final now = DateTime.now();
      double? power;
      double? cadence;
      int? hr;
      List<int> rr = [];
      double? coreTemp;

      for (final c in _connections.values) {
        if (c.status != BleConnectionStatus.connected) continue;
        switch (c.kind) {
          case DeviceKind.roller:
            power = 180 + _rng.nextInt(40).toDouble();
            cadence = 85 + _rng.nextInt(8).toDouble();
          case DeviceKind.heartRate:
            hr = 130 + _rng.nextInt(15);
            rr = [820, 790, 810];
          case DeviceKind.coreTemperature:
            coreTemp = 37.4 + _rng.nextDouble() * 0.3;
        }
      }

      if (_connections.values.any(
        (c) => c.status == BleConnectionStatus.connected,
      )) {
        _snapshot.add(
          PhysiologicalSnapshot(
            timestamp: now,
            powerW: power,
            cadenceRpm: cadence,
            heartRateBpm: hr,
            rrIntervalsMs: rr,
            coreTempC: coreTemp,
          ),
        );
      }
    });
  }

  void _emitDiscovered() => _discovered.add(List.unmodifiable(_scanResults));

  void _emitConnected() =>
      _connected.add(_connections.values.toList(growable: false));

  @override
  Future<void> dispose() async {
    await stopScan();
    _metricsTimer?.cancel();
    await _discovered.close();
    await _connected.close();
    await _snapshot.close();
  }
}
