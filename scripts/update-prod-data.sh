#!/usr/bin/env bash
set -euo pipefail

# scripts/update-prod-data.sh — the roster/question refresh path.
#
# Run this after editing prod/data/participants.csv and re-running
# prod/generate_tokens.py locally (which mints new tokens and rewrites
# manifest.csv). This script pushes prod/data/ to the ops S3 bucket and,
# for participants, re-seeds the live box immediately - no reboot, no
# redeploy, no full ec2-bootstrap.sh run. One command, roughly 10 seconds.
#
# Only participants get a live re-seed here. server_ready_questions.csv is
# loaded into memory at api boot (app/main.py), so a mid-cycle question
# change still needs `docker compose restart api` (see the ops runbook) -
# deliberate, since silently reloading questions under a student mid-attempt
# would be worse than requiring an explicit restart.
#
# Usage (from project root, with AWS SSO session active):
#   ./scripts/update-prod-data.sh

OPS_BUCKET="aitutor-434195712367-ops"
AWS_REGION="us-west-2"

log() { echo "[update-prod-data] $*"; }

if [ ! -f prod/data/manifest.csv ]; then
  echo "ERROR: prod/data/manifest.csv not found. Run prod/generate_tokens.py first." >&2
  exit 1
fi

log "Syncing prod/data/ to s3://${OPS_BUCKET}/artifacts/prod-data/"
aws s3 sync prod/data/ "s3://${OPS_BUCKET}/artifacts/prod-data/" --delete --region "$AWS_REGION"

INSTANCE_ID="$(aws ec2 describe-instances --region "$AWS_REGION" \
  --filters Name=tag:Name,Values=aitutor-app Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)"

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
  log "No running instance found (box is likely stopped between exams)."
  log "S3 is updated - the next boot's ec2-bootstrap.sh will pick this up and seed automatically."
  exit 0
fi

log "Re-seeding participants on running instance $INSTANCE_ID (no reboot)"
# The command goes through a JSON file rather than `--parameters commands="..."`.
# Inline, the single quotes needed for `bash -c` collide with the AWS CLI's own
# shorthand parser, which reads the `'` as a syntax error and aborts:
#   Error parsing parameter '--parameters': Expected: ',', received: '''
# That made this whole script exit 1 at the point where it re-seeds, so the S3
# sync above landed but the live box was never updated - a roster edit looked
# like it had been applied when it had not.
PARAMS_FILE="$(mktemp)"
trap 'rm -f "$PARAMS_FILE"' EXIT
cat > "$PARAMS_FILE" <<JSON
{
  "commands": [
    "cd /home/ec2-user/AITutorApp",
    "sudo -u ec2-user aws s3 sync s3://${OPS_BUCKET}/artifacts/prod-data/ prod/data/ --delete --region ${AWS_REGION}",
    "docker compose exec -T api python prod/seed_participants.py"
  ]
}
JSON

CMD_ID="$(aws ssm send-command --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "file://$PARAMS_FILE" \
  --query 'Command.CommandId' --output text)"

log "Command $CMD_ID sent, waiting for result..."
aws ssm wait command-executed --region "$AWS_REGION" --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" || true

aws ssm get-command-invocation --region "$AWS_REGION" \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Output:StandardOutputContent,Error:StandardErrorContent}' --output json
