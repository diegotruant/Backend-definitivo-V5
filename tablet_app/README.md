# App tablet — Test in presenza

App Flutter per **tablet** usata dal coach durante i test in laboratorio.
Si collega via **BLE** a:

- **Rulli** (smart trainer, FTMS / protocolli vendor)
- **Fascia cardio** (FC + intervalli RR quando disponibili)
- **Sensore temperatura core** (opzionale)

I risultati vengono inviati al backend Digital Twin secondo
[`CONTRATTO_JSON_test.md`](../CONTRATTO_JSON_test.md).

## Architettura

```
lib/
├── core/           # config, tema, routing, errori
├── domain/         # entità e contratti repository (nessuna dipendenza Flutter)
├── data/           # BLE, DTO, implementazioni repository
└── presentation/   # UI Riverpod + go_router
```

| Layer | Responsabilità |
|-------|----------------|
| **domain** | `BleHubRepository`, modelli atleta/test, `PhysiologicalSnapshot` |
| **data** | `FakeBleHub` (dev), `FlutterBleHub` (produzione), classificatore GATT |
| **presentation** | Schermate tablet, provider, widget metriche live |

### BLE — approccio incrementale

1. **Fatto (step 1):** hub astratto, scansione/connessione, UI dispositivi, metriche simulate.
2. **Prossimo:** adapter GATT per FTMS (rullo), Heart Rate + RR, core temp vendor.
3. **Poi:** sessione test per protocollo + invio busta JSON al backend.

`AppConfig.useFakeBle = true` (default) permette sviluppo senza hardware.
Per hardware reale: impostare `useFakeBle: false` in `lib/core/config/app_config.dart`.

## Avvio

```bash
export PATH="/path/to/flutter/bin:$PATH"
cd tablet_app
flutter pub get
flutter run
```

Per build release Android tablet:

```bash
flutter build apk --release
```

## Test

```bash
flutter analyze
flutter test
```

## Permessi

- **Android:** `BLUETOOTH_SCAN`, `BLUETOOTH_CONNECT` in `AndroidManifest.xml`
- **iOS:** chiavi `NSBluetoothAlwaysUsageDescription` in `Info.plist` (da completare al deploy)
