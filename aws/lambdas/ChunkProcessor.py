import json
import boto3
import os
from botocore.exceptions import ClientError

s3_client = boto3.client('s3')
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')

DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
PROCESSED_PARTS_BUCKET = os.environ['PROCESSED_PARTS_BUCKET']
SINGLE_FILE_PACKAGER_NAME = os.environ['SINGLE_FILE_PACKAGER_NAME']

table = dynamodb.Table(DYNAMODB_TABLE_NAME)

def lambda_handler(event, context):
    failed_message_ids = []

    for record in event['Records']:
        try:
            message = json.loads(record['body'])
            task_id = message['taskId']
            bucket = message['bucket']
            key = message['key']
            byte_range = message['byteRange']
            chunk_index = message['chunkIndex']

            response = s3_client.get_object(Bucket=bucket, Key=key, Range=byte_range)
            content_chunk = response['Body'].read().decode('utf-8', errors='ignore')

            lines = content_chunk.splitlines()

            if chunk_index > 0 and lines:
                lines = lines[1:]

            processed_lines = []
            for line in lines:
                if line.strip():
                    processed_lines.append(f"Hello! {line}")
            
            if not processed_lines:
                update_and_check_completion(task_id)
                continue 

            result_content = "\n".join(processed_lines)
            result_key = f"{task_id}/part-{chunk_index:05d}.txt"
            s3_client.put_object(Bucket=PROCESSED_PARTS_BUCKET, Key=result_key, Body=result_content)
            
            update_and_check_completion(task_id)

        except Exception as e:
            print(f"Error processing message. Will be marked for retry. Error: {e}, Message Body: {record['body']}")
            failed_message_ids.append(record['messageId'])

    return {
        'batchItemFailures': [
            {'itemIdentifier': msg_id} for msg_id in failed_message_ids
        ]
    }


def update_and_check_completion(task_id):
    try:
        response = table.update_item(
            Key={'taskId': task_id},
            UpdateExpression="SET completedChunks = completedChunks + :val",
            ExpressionAttributeValues={':val': 1},
            ReturnValues="ALL_NEW"
        )
        
        attributes = response['Attributes']
        completed_chunks = attributes.get('completedChunks', 0)
        total_chunks = attributes.get('totalChunks', -1)
        
        if total_chunks != -1 and completed_chunks >= total_chunks:
            print(f"All chunks for task {task_id} are complete. Invoking packager.")
            lambda_client.invoke(
                FunctionName=SINGLE_FILE_PACKAGER_NAME,
                InvocationType='Event',
                Payload=json.dumps({'taskId': task_id})
            )

    except ClientError as e:
        print(f"Error updating DynamoDB for task {task_id}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in update_and_check_completion for task {task_id}: {e}")