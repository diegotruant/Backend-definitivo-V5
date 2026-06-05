/// UUID GATT standard e servizi noti (FTMS, Heart Rate, ecc.).
abstract final class BleGattProfiles {
  // Heart Rate Service (Bluetooth SIG)
  static const heartRateService = '0000180d-0000-1000-8000-00805f9b34fb';
  static const heartRateMeasurement = '00002a37-0000-1000-8000-00805f9b34fb';

  // Fitness Machine Service (smart trainer / rullo FTMS)
  static const fitnessMachineService = '00001826-0000-1000-8000-00805f9b34fb';
  static const indoorBikeData = '00002ad2-0000-1000-8000-00805f9b34fb';
  static const fitnessMachineControlPoint =
      '00002ad9-0000-1000-8000-00805f9b34fb';

  // Cycling Power (alternativa potenza)
  static const cyclingPowerService = '00001818-0000-1000-8000-00805f9b34fb';
  static const cyclingPowerMeasurement =
      '00002a63-0000-1000-8000-00805f9b34fb';

  // Cycling Speed and Cadence
  static const cscService = '00001816-0000-1000-8000-00805f9b34fb';
}
