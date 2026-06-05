import 'package:equatable/equatable.dart';
import 'package:in_person_test_tablet/domain/entities/ble_connection_status.dart';
import 'package:in_person_test_tablet/domain/entities/device_kind.dart';

/// Dispositivo collegato (o in connessione) gestito dall'hub BLE.
class ConnectedDevice extends Equatable {
  const ConnectedDevice({
    required this.id,
    required this.name,
    required this.kind,
    required this.status,
    this.lastError,
  });

  final String id;
  final String name;
  final DeviceKind kind;
  final BleConnectionStatus status;
  final String? lastError;

  bool get isConnected => status == BleConnectionStatus.connected;

  ConnectedDevice copyWith({
    BleConnectionStatus? status,
    String? lastError,
  }) {
    return ConnectedDevice(
      id: id,
      name: name,
      kind: kind,
      status: status ?? this.status,
      lastError: lastError ?? this.lastError,
    );
  }

  @override
  List<Object?> get props => [id, name, kind, status, lastError];
}
