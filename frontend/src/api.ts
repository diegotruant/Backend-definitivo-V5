/** Re-export typed API client (backward compatible with legacy `./api` imports). */
export { api, ApiError, API_BASE } from './api/client';
export type {
  ApiOperationId,
  CalendarTransitionRequest,
  ConfirmRequest,
  EnginePayload,
  HealthResponse,
  InPersonTestRequest,
  ManualLoadRequest,
  PowerSourceNormalizationRequest,
  SeasonProjectionRequest,
  SnapshotRequest,
  TeamCalibrationApplyRequest,
  TeamCalibrationUpdateRequest,
  TwinStateBuildRequest,
  TwinStateUpdateRideRequest,
  TwinStateUpdateWorkoutRequest,
  UpdateProfileRequest,
  WorkoutFeasibilityRequest,
  WorkoutPrescribeRequest,
  WorkoutPrescribeResponse,
  WorkoutValidateRequest,
} from './api/client';
