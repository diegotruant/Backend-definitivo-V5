import 'package:in_person_test_tablet/domain/entities/device_kind.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';

/// Adapter per un singolo dispositivo BLE connesso.
///
/// Ogni implementazione (FTMS rullo, HR+RR, core temp) traduce il GATT
/// in contributi parziali allo [PhysiologicalSnapshot] aggregato.
abstract class BleDeviceAdapter {
  DeviceKind get kind;

  String get deviceId;

  Future<void> attach();

  Future<void> detach();

  /// Stream di aggiornamenti parziali da questo dispositivo.
  Stream<PhysiologicalSnapshot> watchMetrics();
}
