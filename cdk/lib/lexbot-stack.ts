import * as cdk from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as cloudwatchActions from 'aws-cdk-lib/aws-cloudwatch-actions';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as rds from 'aws-cdk-lib/aws-rds';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as sns from 'aws-cdk-lib/aws-sns';
import * as snsSubscriptions from 'aws-cdk-lib/aws-sns-subscriptions';
import { Construct } from 'constructs';
import { DeployRole } from './deploy-role';

/**
 * LexBot single deployable unit: VPC + ECS Fargate + RDS PostgreSQL 15
 * (pgvector) + ALB (HTTP origin) + CloudFront (HTTPS edge) + ECR +
 * Secrets Manager + budget/memory alarms + GitHub Actions OIDC deploy role.
 *
 * Approved deviation (design D-INF-2): the ALB keeps an HTTP-only listener;
 * TLS terminates at CloudFront with the default `*.cloudfront.net`
 * certificate (no custom domain / ACM / Route 53). Webhook URL is stable:
 * `https://{distributionDomainName}/webhook/telegram`.
 *
 * Context params (required at deploy):
 *   imageTag        — git SHA tagged into ECR; MUST be passed (-c imageTag=)
 * Optional context (defaults in cdk.json):
 *   region, envName, budgetLimitUsd, taskCpu, taskMemoryMiB, budgetEmail,
 *   telegramChatId, corsOrigins, sourceUrlBase, llmModel
 */
export class LexBotStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const ctx = this.node.tryGetContext.bind(this.node);
    const envName = ctx('envName') ?? 'prod';
    const imageTag = ctx('imageTag');
    if (!imageTag) {
      throw new Error(
        'Missing required context param "imageTag" — pass -c imageTag=<git-sha> at deploy/synth',
      );
    }
    const budgetLimitUsd = Number(ctx('budgetLimitUsd') ?? 45);
    const taskCpu = Number(ctx('taskCpu') ?? 512);
    const taskMemoryMiB = Number(ctx('taskMemoryMiB') ?? 1024);
    const budgetEmail = ctx('budgetEmail') ?? 'alerts@example.com';
    const telegramChatId = ctx('telegramChatId') ?? '';
    const corsOrigins = ctx('corsOrigins') ?? 'http://localhost:5173';
    const sourceUrlBase =
      ctx('sourceUrlBase') ?? 'https://github.com/CarlosDiazData/lexbot/blob/main/docs/knowledge';
    const llmModel = ctx('llmModel') ?? '';

    cdk.Tags.of(this).add('app', 'lexbot');
    cdk.Tags.of(this).add('env', envName);

    // --- VPC (maxAzs 2, single NAT gateway to stay inside the $45 budget) ---
    const vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 1,
    });

    // --- ECR (stable repository name so CI can docker push without lookups) ---
    const repo = new ecr.Repository(this, 'Repo', {
      repositoryName: 'lexbot',
      imageScanOnPush: true,
    });

    // --- RDS PostgreSQL 15 (single-AZ, generated master secret) ---
    // RemovalPolicy.SNAPSHOT maps the design's "DESTROY + final snapshot":
    // CloudFormation deletes the instance on stack removal but retains a
    // final snapshot (DeletionPolicy: Snapshot is also the CFN default for
    // standalone DB instances).
    const database = new rds.DatabaseInstance(this, 'Database', {
      engine: rds.DatabaseInstanceEngine.postgres({
        version: rds.PostgresEngineVersion.VER_15_5,
      }),
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL),
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      credentials: rds.Credentials.fromGeneratedSecret('lexbot', {
        secretName: 'lexbot/rds/master',
      }),
      databaseName: 'lexbot',
      port: 5432,
      multiAz: false,
      storageEncrypted: true,
      removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
      backupRetention: cdk.Duration.days(7),
    });
    const dbSecret = database.secret!;

    // --- Log group (awslogs driver for the Fargate container) ---
    const logGroup = new logs.LogGroup(this, 'LogGroup', {
      logGroupName: '/ecs/lexbot',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // --- App secrets (placeholders, filled once before first deploy) ---
    // Values are JSON objects; the container extracts the named field, e.g.
    // {"telegram_bot_token":"<real token>"}. generateSecretString keeps the
    // placeholder out of the CloudFormation template.
    const botTokenSecret = new secretsmanager.Secret(this, 'TelegramBotTokenSecret', {
      secretName: 'lexbot/telegram/bot-token',
      description: 'Telegram bot token — set value to {"telegram_bot_token":"<token>"} before deploy',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ telegram_bot_token: 'PLACEHOLDER' }),
        generateStringKey: 'random',
        excludePunctuation: true,
      },
    });
    const webhookSecret = new secretsmanager.Secret(this, 'TelegramWebhookSecret', {
      secretName: 'lexbot/telegram/webhook-secret',
      description:
        'Telegram webhook secret token — set value to {"telegram_webhook_secret":"<secret>"} before deploy',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ telegram_webhook_secret: 'PLACEHOLDER' }),
        generateStringKey: 'random',
        excludePunctuation: true,
      },
    });
    const geminiKeySecret = new secretsmanager.Secret(this, 'GeminiApiKeySecret', {
      secretName: 'lexbot/gemini/api-key',
      description: 'Google Gemini API key — set value to {"gemini_api_key":"<key>"} before deploy',
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ gemini_api_key: 'PLACEHOLDER' }),
        generateStringKey: 'random',
        excludePunctuation: true,
      },
    });

    // --- ALB (HTTP-only origin for CloudFront — approved deviation) ---
    const alb = new elbv2.ApplicationLoadBalancer(this, 'Alb', {
      vpc,
      internetFacing: true,
    });
    const listener = alb.addListener('HttpListener', {
      port: 80,
      open: true,
    });

    // --- CloudFront: HTTPS edge with default *.cloudfront.net cert ---
    // CachingDisabled + ALL_VIEWER origin request policy forward ALL headers
    // so X-Telegram-Bot-Api-Secret-Token reaches Fargate, and POST/PUT/DELETE
    // pass through for /webhook/telegram and /chat.
    const distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: 'LexBot HTTPS edge (default *.cloudfront.net certificate)',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      defaultBehavior: {
        origin: new origins.HttpOrigin(alb.loadBalancerDnsName, {
          protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
        }),
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
    });

    // --- ECS: cluster + task definition + Fargate service ---
    const cluster = new ecs.Cluster(this, 'Cluster', {
      vpc,
      containerInsightsV2: ecs.ContainerInsights.ENABLED,
    });

    const taskDef = new ecs.FargateTaskDefinition(this, 'TaskDef', {
      cpu: taskCpu,
      memoryLimitMiB: taskMemoryMiB,
    });

    // DATABASE_URL is composed at deploy time (design INF-3): generated-secret
    // password + RDS endpoint, resolved via the Secrets Manager dynamic
    // reference by ECS at task launch. The execution role therefore needs
    // GetSecretValue on the RDS master secret (not auto-added for plain env).
    const databaseUrl = cdk.Fn.join('', [
      'postgresql://',
      dbSecret.secretValueFromJson('username').unsafeUnwrap(),
      ':',
      dbSecret.secretValueFromJson('password').unsafeUnwrap(),
      '@',
      database.dbInstanceEndpointAddress,
      ':',
      database.dbInstanceEndpointPort,
      '/lexbot',
    ]);
    taskDef.executionRole?.addToPrincipalPolicy(
      new iam.PolicyStatement({
        actions: ['secretsmanager:GetSecretValue'],
        resources: [dbSecret.secretArn],
      }),
    );

    const webhookUrl = cdk.Fn.join('', [
      'https://',
      distribution.distributionDomainName,
      '/webhook/telegram',
    ]);

    const environment: Record<string, string> = {
      TELEGRAM_WEBHOOK_URL: webhookUrl,
      TELEGRAM_CHAT_ID: telegramChatId,
      STORE_PROVIDER: 'pgvector',
      LLM_PROVIDER: 'gemini',
      EMBEDDING_PROVIDER: 'gemini',
      CORS_ORIGINS: corsOrigins,
      SOURCE_URL_BASE: sourceUrlBase,
      DATABASE_URL: databaseUrl,
    };
    if (llmModel) {
      environment.LLM_MODEL = llmModel;
    }

    const container = taskDef.addContainer('App', {
      image: ecs.ContainerImage.fromEcrRepository(repo, imageTag),
      portMappings: [{ containerPort: 8000, protocol: ecs.Protocol.TCP }],
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'lexbot', logGroup }),
      environment,
      secrets: {
        TELEGRAM_BOT_TOKEN: ecs.Secret.fromSecretsManager(botTokenSecret, 'telegram_bot_token'),
        TELEGRAM_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(webhookSecret, 'telegram_webhook_secret'),
        GEMINI_API_KEY: ecs.Secret.fromSecretsManager(geminiKeySecret, 'gemini_api_key'),
      },
    });
    void container;

    const service = new ecs.FargateService(this, 'Service', {
      cluster,
      taskDefinition: taskDef,
      desiredCount: 1,
      healthCheckGracePeriod: cdk.Duration.seconds(300),
      // Keep the previous release serving while a new task comes up
      // (smoke gate fails the deploy, old task still answers).
      minHealthyPercent: 100,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      assignPublicIp: false,
    });

    listener.addTargets('FargateTargets', {
      port: 8000,
      targets: [service],
      healthCheck: {
        path: '/health',
        healthyHttpCodes: '200',
      },
    });

    // --- Budget: $45/month → SNS → email ---
    const budgetTopic = new sns.Topic(this, 'BudgetTopic', {
      displayName: 'lexbot-budget-alerts',
    });
    budgetTopic.addSubscription(new snsSubscriptions.EmailSubscription(budgetEmail));
    new budgets.CfnBudget(this, 'Budget', {
      budget: {
        budgetName: 'lexbot-monthly',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: budgetLimitUsd, unit: 'USD' },
      },
      notificationsWithSubscribers: [
        {
          notification: {
            comparisonOperator: 'GREATER_THAN',
            notificationType: 'ACTUAL',
            threshold: 100,
            thresholdType: 'PERCENTAGE',
          },
          subscribers: [{ subscriptionType: 'SNS', address: budgetTopic.topicArn }],
        },
      ],
    });

    // --- Memory alarm: Container Insights MemoryUtilized ≥ 85% (10 min) ---
    const memoryAlarm = new cloudwatch.Alarm(this, 'MemoryAlarm', {
      alarmDescription: `ECS service memory >= 85% of ${taskMemoryMiB} MiB for 10 minutes`,
      metric: new cloudwatch.Metric({
        namespace: 'ECS/ContainerInsights',
        metricName: 'MemoryUtilized',
        dimensionsMap: {
          ClusterName: cluster.clusterName,
          ServiceName: service.serviceName,
        },
        period: cdk.Duration.minutes(10),
        statistic: 'Average',
      }),
      threshold: Math.round(taskMemoryMiB * 0.85),
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      actionsEnabled: true,
    });
    memoryAlarm.addAlarmAction(new cloudwatchActions.SnsAction(budgetTopic));

    // --- GitHub Actions OIDC deploy role (CI-1, no static keys) ---
    const deployRole = new DeployRole(this, 'DeployRole', {
      githubOrg: 'CarlosDiazData',
      githubRepo: 'lexbot',
      ecrRepository: repo,
      ecsCluster: cluster,
      ecsService: service,
      taskRoleArn: taskDef.taskRole.roleArn,
      executionRoleArn: taskDef.executionRole!.roleArn,
      appSecretArns: [botTokenSecret.secretArn, webhookSecret.secretArn, geminiKeySecret.secretArn],
    });

    // --- Outputs (consumed by CI smoke + README + workflow) ---
    new cdk.CfnOutput(this, 'CloudFrontDomain', {
      value: distribution.distributionDomainName,
      description: 'HTTPS endpoint (webhook base URL)',
    });
    new cdk.CfnOutput(this, 'WebhookUrl', {
      value: webhookUrl,
      description: 'Telegram webhook URL (stable across deploys)',
    });
    new cdk.CfnOutput(this, 'LoadBalancerDns', {
      value: alb.loadBalancerDnsName,
      description: 'ALB HTTP origin DNS (internal)',
    });
    new cdk.CfnOutput(this, 'EcrRepositoryUri', {
      value: repo.repositoryUri,
      description: 'ECR repository for the app image',
    });
    new cdk.CfnOutput(this, 'DeployRoleArn', {
      value: deployRole.role.roleArn,
      description: 'GitHub Actions OIDC deploy role ARN',
    });
  }
}