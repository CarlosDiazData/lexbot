import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { DeployRole } from '../lib/deploy-role';

function makeStack(): { template: Template } {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, 'TestStack', {
    env: { account: '111122223333', region: 'us-east-1' },
  });

  const repo = new ecr.Repository(stack, 'Repo', { repositoryName: 'lexbot' });
  const vpc = new ec2.Vpc(stack, 'Vpc', { maxAzs: 1, natGateways: 1 });
  const cluster = new ecs.Cluster(stack, 'Cluster', { vpc });
  const executionRole = new iam.Role(stack, 'ExecRole', {
    assumedBy: new iam.ServicePrincipal('ecs-tasks.amazonaws.com'),
  });
  const taskDef = new ecs.FargateTaskDefinition(stack, 'TaskDef', {
    cpu: 512,
    memoryLimitMiB: 1024,
    executionRole,
  });
  taskDef.addContainer('App', {
    image: ecs.ContainerImage.fromRegistry('example.invalid/lexbot:test'),
  });
  const service = new ecs.FargateService(stack, 'Service', {
    cluster,
    taskDefinition: taskDef,
    desiredCount: 1,
  });
  const secret = new secretsmanager.Secret(stack, 'AppSecret');

  new DeployRole(stack, 'DeployRole', {
    githubOrg: 'CarlosDiazData',
    githubRepo: 'lexbot',
    ecrRepository: repo,
    ecsCluster: cluster,
    ecsService: service,
    taskRoleArn: taskDef.taskRole.roleArn,
    executionRoleArn: taskDef.executionRole!.roleArn,
    appSecretArns: [secret.secretArn],
  });

  return { template: Template.fromStack(stack) };
}

describe('DeployRole', () => {
  test('creates the GitHub OIDC provider with the documented thumbprint', () => {
    const { template } = makeStack();
    // Recent aws-cdk-lib versions back the OIDC provider with a custom
    // resource (thumbprint auto-management); the deployed provider carries
    // the documented URL, client id and GitHub thumbprint.
    template.resourceCountIs('Custom::AWSCDKOpenIdConnectProvider', 1);
    template.hasResourceProperties('Custom::AWSCDKOpenIdConnectProvider', {
      Url: 'https://token.actions.githubusercontent.com',
      ClientIDList: ['sts.amazonaws.com'],
      ThumbprintList: ['6938fd4d98bab03faadb97b34396831e3780aea1'],
    });
  });

  test('role is assumed only by the lexbot repo via web identity (no static keys)', () => {
    const { template } = makeStack();
    template.hasResourceProperties('AWS::IAM::Role', {
      AssumeRolePolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: 'sts:AssumeRoleWithWebIdentity',
            Condition: {
              StringEquals: { 'token.actions.githubusercontent.com:aud': 'sts.amazonaws.com' },
              StringLike: {
                'token.actions.githubusercontent.com:sub': 'repo:CarlosDiazData/lexbot:*',
              },
            },
          }),
        ]),
      },
    });
    // No static credentials anywhere
    template.resourceCountIs('AWS::IAM::AccessKey', 0);
  });

  test('grants least-privilege deploy actions only', () => {
    const { template } = makeStack();

    // Order-independent check: flatten every Action from the inline policy
    // (single-action statements render as strings, multi-action as arrays).
    const policies = template.findResources('AWS::IAM::Policy');
    expect(Object.keys(policies)).toHaveLength(1);
    const statements = Object.values(policies)[0].Properties.PolicyDocument.Statement as Array<{
      Action: string | string[];
      Resource?: unknown;
    }>;
    const actions = statements.flatMap((s) => (Array.isArray(s.Action) ? s.Action : [s.Action]));

    expect(actions).toEqual(
      expect.arrayContaining([
        // CloudFormation scoped to the app stack
        'cloudformation:UpdateStack',
        'cloudformation:CreateChangeSet',
        'cloudformation:DescribeStacks',
        // S3 scoped to the CDKToolkit asset bucket
        's3:PutObject',
        's3:GetObject',
        // ECR push on the repo only
        'ecr:PutImage',
        'ecr:CompleteLayerUpload',
        // ECS service updates + task definition registration
        'ecs:UpdateService',
        'ecs:RegisterTaskDefinition',
        // PassRole on ECS + bootstrap roles
        'iam:PassRole',
        // Secrets: the 3 app secrets
        'secretsmanager:GetSecretValue',
        // CloudWatch metrics for the smoke/load check
        'cloudwatch:GetMetricData',
      ]),
    );

    // No wildcard-only statements outside the account-scoped exceptions
    const wildcardResources = statements.filter((s) => s.Resource === '*');
    expect(wildcardResources.length).toBeGreaterThan(0); // ListStacks/ValidateTemplate/ecr token/ecs taskdef/cloudwatch
  });
});