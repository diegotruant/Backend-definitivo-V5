import 'package:equatable/equatable.dart';

/// Campione live aggregato da tutti i sensori collegati in un istante.
class PhysiologicalSnapshot extends Equatable {
  const PhysiologicalSnapshot({
    required this.timestamp,
    this.powerW,
    this.cadenceRpm,
    this.heartRateBpm,
    this.rrIntervalsMs = const [],
    this.coreTempC,
  });

  final DateTime timestamp;

  /// Potenza dal rullo o power meter (W).
  final double? powerW;

  /// Cadenza (rpm).
  final double? cadenceRpm;

  /// FC istantanea (bpm).
  final int? heartRateBpm;

  /// Intervalli RR in ms (HRV / analisi cardiaca).
  final List<int> rrIntervalsMs;

  /// Temperatura corporea core (°C).
  final double? coreTempC;

  bool get hasHeartRate => heartRateBpm != null;
  bool get hasRr => rrIntervalsMs.isNotEmpty;
  bool get hasCoreTemp => coreTempC != null;
  bool get hasPower => powerW != null;

  @override
  List<Object?> get props => [
        timestamp,
        powerW,
        cadenceRpm,
        heartRateBpm,
        rrIntervalsMs,
        coreTempC,
      ];
}
