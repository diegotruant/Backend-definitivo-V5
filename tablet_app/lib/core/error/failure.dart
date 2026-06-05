import 'package:equatable/equatable.dart';

/// Errore di dominio / infrastruttura, indipendente da Flutter.
sealed class Failure extends Equatable {
  const Failure(this.message);

  final String message;

  @override
  List<Object?> get props => [message];
}

final class BleFailure extends Failure {
  const BleFailure(super.message, {this.code});

  final String? code;

  @override
  List<Object?> get props => [message, code];
}

final class NetworkFailure extends Failure {
  const NetworkFailure(super.message);
}

final class ValidationFailure extends Failure {
  const ValidationFailure(super.message);
}
