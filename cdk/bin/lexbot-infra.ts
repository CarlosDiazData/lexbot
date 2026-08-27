#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { LexBotStack } from '../lib/lexbot-stack';

const app = new cdk.App();

const region = app.node.tryGetContext('region') ?? process.env.CDK_DEFAULT_REGION ?? 'us-east-1';
const envName = app.node.tryGetContext('envName') ?? 'prod';

new LexBotStack(app, 'LexBotStack', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region },
  description: `LexBot production infrastructure (env=${envName})`,
});

app.synth();