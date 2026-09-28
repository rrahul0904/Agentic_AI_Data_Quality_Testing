type MinimalPlan = {
  mode?: string;
  steps: Array<{ kind: string }>;
};

/** Previously saved one-step DAG plans must not retain an end-to-end approval path. */
export function isIncompleteEndToEnd(plan: MinimalPlan | null | undefined): boolean {
  return plan?.mode === "end_to_end" && plan.steps.length === 1 && plan.steps[0]?.kind === "airflow_trigger";
}
