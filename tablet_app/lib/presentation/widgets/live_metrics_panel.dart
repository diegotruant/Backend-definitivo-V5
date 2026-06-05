import 'package:flutter/material.dart';
import 'package:in_person_test_tablet/domain/entities/physiological_snapshot.dart';

/// Pannello metriche live durante test / connessione dispositivi.
class LiveMetricsPanel extends StatelessWidget {
  const LiveMetricsPanel({super.key, required this.snapshot});

  final PhysiologicalSnapshot snapshot;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Metriche live', style: theme.textTheme.titleMedium),
            const SizedBox(height: 16),
            Wrap(
              spacing: 24,
              runSpacing: 16,
              children: [
                _MetricChip(
                  label: 'Potenza',
                  value: snapshot.hasPower
                      ? '${snapshot.powerW!.round()} W'
                      : '—',
                  icon: Icons.bolt,
                ),
                _MetricChip(
                  label: 'Cadenza',
                  value: snapshot.cadenceRpm != null
                      ? '${snapshot.cadenceRpm!.round()} rpm'
                      : '—',
                  icon: Icons.rotate_right,
                ),
                _MetricChip(
                  label: 'FC',
                  value: snapshot.hasHeartRate
                      ? '${snapshot.heartRateBpm} bpm'
                      : '—',
                  icon: Icons.favorite,
                ),
                _MetricChip(
                  label: 'RR',
                  value: snapshot.hasRr
                      ? '${snapshot.rrIntervalsMs.length} bat'
                      : '—',
                  icon: Icons.monitor_heart,
                ),
                _MetricChip(
                  label: 'Core temp',
                  value: snapshot.hasCoreTemp
                      ? '${snapshot.coreTempC!.toStringAsFixed(1)} °C'
                      : '—',
                  icon: Icons.thermostat,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return SizedBox(
      width: 160,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 18, color: theme.colorScheme.primary),
              const SizedBox(width: 6),
              Text(label, style: theme.textTheme.labelLarge),
            ],
          ),
          const SizedBox(height: 4),
          Text(value, style: theme.textTheme.headlineSmall),
        ],
      ),
    );
  }
}
