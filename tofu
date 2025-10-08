# .gitlab-ci.yml — OpenTofu pipeline
# Assumes your IaC lives under infra/ (override TF_DIR if needed)

image: opentofu/opentofu:1.8.2

stages:
  - validate
  - plan
  - apply
  - destroy

default:
  before_script:
    - apk add --no-cache git curl jq
    - cd "$TF_DIR"
    - tofu --version
  cache:
    key:
      files:
        - $TF_DIR/.terraform.lock.hcl
    paths:
      - $TF_DIR/.terraform/
  variables:
    TF_DIR: infra
    TF_IN_AUTOMATION: "true"
    TF_INPUT: "false"
    TF_CLI_ARGS: "-no-color"
    TOFU_LOG: "WARN"            # set to INFO/DEBUG when needed
    TOFU_WORKSPACE: "${CI_COMMIT_REF_SLUG}"   # or "default", or map via rules
    PLAN_FILE: "plan.tfplan"

.tofu:init:
  script:
    - tofu workspace list || true
    - |
      if tofu workspace select "$TOFU_WORKSPACE"; then
        echo "Selected workspace $TOFU_WORKSPACE"
      else
        tofu workspace new "$TOFU_WORKSPACE"
      fi
    - tofu init -upgrade

validate:
  stage: validate
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH
  extends: .tofu:init
  script:
    - tofu fmt -recursive -check
    - tofu validate

plan:
  stage: plan
  needs: ["validate"]
  rules:
    # Run on merge requests and branch pushes, but not on tags
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_COMMIT_TAG == null
  extends: .tofu:init
  script:
    # Optional: pass metadata into TF as vars (make them TF_VAR_* in GitLab settings)
    - tofu plan -out "$PLAN_FILE"
    - tofu show -json "$PLAN_FILE" | jq '.' > plan.json
  artifacts:
    when: always
    expire_in: 7 days
    paths:
      - $TF_DIR/$PLAN_FILE
      - $TF_DIR/plan.json
      - $TF_DIR/.terraform.lock.hcl
  variables:
    GIT_STRATEGY: fetch

apply:
  stage: apply
  needs: ["plan"]
  rules:
    # Manual apply on your main line only
    - if: $CI_COMMIT_BRANCH == "main"
      when: manual
      allow_failure: false
  extends: .tofu:init
  script:
    - test -f "$PLAN_FILE" || { echo "Plan file missing. Rerun plan stage."; exit 1; }
    - tofu apply -auto-approve "$PLAN_FILE"
  dependencies:
    - plan
  environment:
    name: $TOFU_WORKSPACE
    action: start

destroy:
  stage: destroy
  rules:
    # Protected manual destroy. Set APPROVE_DESTROY=true when triggering.
    - if: $APPROVE_DESTROY == "true"
      when: manual
      allow_failure: false
  extends: .tofu:init
  script:
    - tofu plan -destroy -out "$PLAN_FILE"
    - tofu apply -auto-approve "$PLAN_FILE"
  environment:
    name: $TOFU_WORKSPACE
    action: stop
