import 'package:equatable/equatable.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';

/// Dispositivo visto in scansione BLE, prima della connessione.
class DiscoveredDevice extends Equatable {
  const DiscoveredDevice({
    required this.id,
    required this.name,
    required this.kind,
    required this.rssi,
  });

  final String id;
  final String name;
  final DeviceKind kind;
  final int rssi;

  @override
  List<Object?> get props => [id, name, kind, rssi];
}
