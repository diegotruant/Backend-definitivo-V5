import 'package:equatable/equatable.dart';

enum AthleteRegistrationType { registered, guest }

/// Profilo atleta per busta JSON test (CONTRATTO_JSON_test.md).
class AthleteProfile extends Equatable {
  const AthleteProfile({
    this.id,
    required this.type,
    this.name,
    this.surname,
    this.dob,
    this.weightKg,
    this.heightCm,
    this.sex,
    this.hrMax,
  });

  final String? id;
  final AthleteRegistrationType type;
  final String? name;
  final String? surname;
  final DateTime? dob;
  final double? weightKg;
  final double? heightCm;
  final String? sex;
  final int? hrMax;

  Map<String, dynamic> toJson() => {
        'id': id,
        'type': type == AthleteRegistrationType.registered
            ? 'registered'
            : 'guest',
        if (name != null) 'name': name,
        if (surname != null) 'surname': surname,
        if (dob != null) 'dob': _formatDate(dob!),
        if (weightKg != null) 'weight_kg': weightKg,
        if (heightCm != null) 'height_cm': heightCm,
        if (sex != null) 'sex': sex,
        if (hrMax != null) 'hr_max': hrMax,
      };

  static String _formatDate(DateTime d) =>
      '${d.year.toString().padLeft(4, '0')}-'
      '${d.month.toString().padLeft(2, '0')}-'
      '${d.day.toString().padLeft(2, '0')}';

  @override
  List<Object?> get props =>
      [id, type, name, surname, dob, weightKg, heightCm, sex, hrMax];
}
