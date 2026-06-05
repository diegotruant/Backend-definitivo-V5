/// Tipi di test in presenza — allineati a CONTRATTO_JSON_test.md.
enum InPersonTestType {
  mader('mader'),
  incrementale('incrementale'),
  curvaPc('curva_pc'),
  criticalPower('critical_power'),
  wingate('wingate');

  const InPersonTestType(this.apiValue);

  final String apiValue;

  String get label => switch (this) {
        InPersonTestType.mader => 'Mader (lattato)',
        InPersonTestType.incrementale => 'Incrementale',
        InPersonTestType.curvaPc => 'Curva P/C',
        InPersonTestType.criticalPower => 'Critical Power',
        InPersonTestType.wingate => 'Wingate',
      };
}
