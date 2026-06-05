/// Tipi di dispositivo BLE supportati dall'app.
enum DeviceKind {
  /// Rullo / smart trainer (FTMS o protocollo vendor).
  roller,

  /// Fascia cardio standard (GATT Heart Rate, opz. RR).
  heartRate,

  /// Sensore temperatura corporea core (vendor-specific).
  coreTemperature,
}

extension DeviceKindX on DeviceKind {
  String get label => switch (this) {
        DeviceKind.roller => 'Rullo',
        DeviceKind.heartRate => 'Frequenza cardiaca',
        DeviceKind.coreTemperature => 'Temperatura core',
      };

  String get iconName => switch (this) {
        DeviceKind.roller => 'directions_bike',
        DeviceKind.heartRate => 'favorite',
        DeviceKind.coreTemperature => 'thermostat',
      };
}
