import 'package:equatable/equatable.dart';

/// Metadati dispositivo nella busta test (trainer, fonte potenza, modalità).
class TestDeviceInfo extends Equatable {
  const TestDeviceInfo({
    this.trainer,
    this.powerSource,
    this.controlMode,
  });

  final String? trainer;
  final String? powerSource;
  final String? controlMode;

  Map<String, dynamic> toJson() => {
        if (trainer != null) 'trainer': trainer,
        if (powerSource != null) 'power_source': powerSource,
        if (controlMode != null) 'control_mode': controlMode,
      };

  @override
  List<Object?> get props => [trainer, powerSource, controlMode];
}
