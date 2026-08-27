import * as cdk from 'aws-cdk-lib';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

/**
 * GitHub Actions OIDC deploy role (CI-1): assumed by the `aws-actions/
 * configure-aws-credentials` step in the deploy workflow with no static keys.
 *
 * Scope is least-privilege:
 *  - CloudFormation: only the LexBot stack (create/update/change-set ops +
 *    read actions for `cdk diff`).
 *  - S3: only the CDK bootstrap asset bucket (template + asset upload).
 *  - ECR: token + push on the app repository only.
 *  - ECS: service updates / task definition registration for this cluster.
 *  - IAM: PassRole on the ECS task/execution roles and the bootstrap CFN
 *    execution role (required by `cdk deploy` on a bootstrapped account).
 *  - Secrets Manager: read the 3 app secrets.
 *  - CloudWatch: GetMetricData for the smoke/load check.
 *
 * `cdk deploy` also assumes the account's bootstrap roles
 * (`cdk-hnb659fds-file-publishing-role` / `cdk-hnb659fds-cfn-exec-role`);
 * without `sts:AssumeRole` + `iam:PassRole` on those, the workflow deploy
 * fails with AccessDenied on a bootstrapped account.
 */
export interface DeployRoleProps {
  /** GitHub org that owns the repository, e.g. "CarlosDiazData". */
  readonly githubOrg: string;
  /** GitHub repository name, e.g. "lexbot". */
  readonly githubRepo: string;
  /** ECR repository the workflow pushes images to. */
  readonly ecrRepository: ecr.IRepository;
  /** ECS cluster the workflow updates. */
  readonly ecsCluster: ecs.ICluster;
  /** ECS service the workflow restarts. */
  readonly ecsService: ecs.IService;
  /** ARN of the Fargate task role (for iam:PassRole). */
  readonly taskRoleArn: string;
  /** ARN of the Fargate execution role (for iam:PassRole). */
  readonly executionRoleArn: string;
  /** ARNs of the app secrets the container reads (GetSecretValue). */
  readonly appSecretArns: string[];
}

export class DeployRole extends Construct {
  public readonly role: iam.Role;

  constructor(scope: Construct, id: string, props: DeployRoleProps) {
    super(scope, id);

    const stack = cdk.Stack.of(this);

    const provider = new iam.OpenIdConnectProvider(this, 'GithubOidcProvider', {
      url: 'https://token.actions.githubusercontent.com',
      clientIds: ['sts.amazonaws.com'],
      // GitHub's OIDC signing cert thumbprint (documented constant).
      thumbprints: ['6938fd4d98bab03faadb97b34396831e3780aea1'],
    });

    this.role = new iam.Role(this, 'GithubDeployRole', {
      assumedBy: new iam.OpenIdConnectPrincipal(provider).withConditions({
        StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
        StringLike: { 'token.actions.githubusercontent.com:sub': `repo:${props.githubOrg}/${props.githubRepo}:*` },
      }),
      description: `GitHub Actions OIDC deploy role for ${props.githubOrg}/${props.githubRepo}`,
    });

    const cfnStackArn = cdk.Arn.format(
      {
        service: 'cloudformation',
        resource: 'stack',
        resourceName: `${stack.stackName}/*`,
        region: cdk.Aws.REGION,
        account: cdk.Aws.ACCOUNT_ID,
      },
      stack,
    );

    // CloudFormation: app stack only (+ account-scoped read actions).
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          'cloudformation:CreateStack',
          'cloudformation:UpdateStack',
          'cloudformation:CreateChangeSet',
          'cloudformation:ExecuteChangeSet',
          'cloudformation:DescribeChangeSet',
          'cloudformation:DeleteChangeSet',
          'cloudformation:DescribeStacks',
          'cloudformation:DescribeStackEvents',
          'cloudformation:GetTemplate',
          'cloudformation:GetTemplateSummary',
        ],
        resources: [cfnStackArn],
      }),
    );
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['cloudformation:ListStacks', 'cloudformation:ValidateTemplate'],
        resources: ['*'],
      }),
    );

    // CDK bootstrap asset bucket (default bootstrap naming).
    const toolkitBucket = `cdk-hnb659fds-assets-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`;
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['s3:GetObject', 's3:PutObject', 's3:DeleteObject', 's3:GetBucketLocation'],
        resources: [
          `arn:${cdk.Aws.PARTITION}:s3:::${toolkitBucket}`,
          `arn:${cdk.Aws.PARTITION}:s3:::${toolkitBucket}/*`,
        ],
      }),
    );

    // ECR: authorization token is account-scoped; push scoped to the repo.
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ecr:GetAuthorizationToken'],
        resources: ['*'],
      }),
    );
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: [
          'ecr:BatchCheckLayerAvailability',
          'ecr:GetDownloadUrlForLayer',
          'ecr:InitiateLayerUpload',
          'ecr:UploadLayerPart',
          'ecr:CompleteLayerUpload',
          'ecr:PutImage',
          'ecr:BatchGetImage',
        ],
        resources: [props.ecrRepository.repositoryArn],
      }),
    );

    // ECS: update/describe the deployed service; task definitions are
    // account-scoped resources.
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:UpdateService', 'ecs:DescribeServices', 'ecs:ListTasks'],
        resources: [props.ecsCluster.clusterArn, props.ecsService.serviceArn],
      }),
    );
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['ecs:RegisterTaskDefinition', 'ecs:DescribeTaskDefinition'],
        resources: ['*'],
      }),
    );

    // PassRole: ECS task + execution roles, and the bootstrap CFN execution
    // role that `cdk deploy` passes to CloudFormation.
    const bootstrapCfnExecRole = `arn:${cdk.Aws.PARTITION}:iam::${cdk.Aws.ACCOUNT_ID}:role/cdk-hnb659fds-cfn-exec-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`;
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['iam:PassRole'],
        resources: [props.taskRoleArn, props.executionRoleArn, bootstrapCfnExecRole],
      }),
    );

    // Bootstrap role assumption (file publishing + CFN execution).
    const bootstrapFilePublishRole = `arn:${cdk.Aws.PARTITION}:iam::${cdk.Aws.ACCOUNT_ID}:role/cdk-hnb659fds-file-publishing-role-${cdk.Aws.ACCOUNT_ID}-${cdk.Aws.REGION}`;
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['sts:AssumeRole'],
        resources: [bootstrapFilePublishRole, bootstrapCfnExecRole],
      }),
    );

    // App secrets (3) read by the container.
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: props.appSecretArns,
      }),
    );

    // Smoke/load check reads Container Insights metrics (account-scoped).
    this.role.addToPolicy(
      new iam.PolicyStatement({
        actions: ['cloudwatch:GetMetricData'],
        resources: ['*'],
      }),
    );
  }
}