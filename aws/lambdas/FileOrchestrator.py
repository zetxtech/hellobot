import json
import boto3
import os
import urllib.parse

s3_client = boto3.client('s3')
sqs_client = boto3.client('sqs')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE_NAME'])
SQS_QUEUE_URL = os.environ['SQS_QUEUE_URL']
PROCESSED_INDIVIDUAL_BUCKET = os.environ['PROCESSED_INDIVIDUAL_BUCKET']

CHUNK_SIZE_BYTES = 1024 * 1024  # 1 MB
LOOKAHEAD_BUFFER_BYTES = 4 * 1024  # 4 KB

def lambda_handler(event, context):
    bucket = event['Records'][0]['s3']['bucket']['name']
    key = urllib.parse.unquote_plus(event['Records'][0]['s3']['object']['key'], encoding='utf-8')
    task_id = key.split('/')[0]

    try:
        response = s3_client.head_object(Bucket=bucket, Key=key)
        total_size = response['ContentLength']
    except Exception as e:
        print(f"FATAL: Could not read file metadata for {key}. Error: {e}")
        table.update_item(
            Key={'taskId': task_id},
            UpdateExpression="SET taskStatus = :s",
            ExpressionAttributeValues={':s': 'FAILED'}
        )
        raise

    if total_size == 0:
        print(f"Task {task_id}: Empty file detected. Finalizing task directly.")
        
        processed_key = f"{task_id}/{original_filename}"
        
        s3_client.put_object(
            Bucket=PROCESSED_INDIVIDUAL_BUCKET,
            Key=processed_key,
            Body=b'',  # Empty content
            ContentType='text/plain'
        )
        
        processed_file_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': PROCESSED_INDIVIDUAL_BUCKET, 'Key': processed_key},
            ExpiresIn=86400  # 24 hours
        )

        # Update DynamoDB to COMPLETED status
        table.update_item(
            Key={'taskId': task_id},
            UpdateExpression="SET taskStatus = :s, totalChunks = :tc, completedChunks = :cc, processedFileUrl = :u, originalFilename = :ofn",
            ExpressionAttributeValues={
                ':s': 'COMPLETED',
                ':tc': 0,
                ':cc': 0,
                ':u': processed_file_url,
                ':ofn': original_filename
            }
        )
        
        try:
            print(f"Cleaning up original empty file {key} from bucket {bucket}.")
            s3_client.delete_object(Bucket=bucket, Key=key)
        except Exception as e:
            print(f"Error cleaning up original empty file for task {task_id}: {e}")
            
        return {'statusCode': 200, 'body': 'Empty file processed and finalized.'}

    messages_to_send = []
    chunk_index = 0
    current_start_byte = 0

    while current_start_byte < total_size:
        potential_end_byte = min(current_start_byte + CHUNK_SIZE_BYTES, total_size)
        actual_end_byte = potential_end_byte

        if potential_end_byte < total_size:
            try:
                range_to_read = f"bytes={potential_end_byte}-{potential_end_byte + LOOKAHEAD_BUFFER_BYTES}"
                response = s3_client.get_object(Bucket=bucket, Key=key, Range=range_to_read)
                buffer = response['Body'].read()

                newline_pos = buffer.find(b'\n')
                
                if newline_pos != -1:
                    actual_end_byte = potential_end_byte + newline_pos

            except s3_client.exceptions.InvalidRange:
                actual_end_byte = total_size
            except Exception as e:
                print(f"WARN: Could not perform lookahead read for chunk {chunk_index}. Using theoretical boundary. Error: {e}")
                actual_end_byte = potential_end_byte
        
        byte_range = f"bytes={current_start_byte}-{actual_end_byte}"
        
        messages_to_send.append({
            'taskId': task_id,
            'bucket': bucket,
            'key': key,
            'chunkIndex': chunk_index,
            'byteRange': byte_range
        })
        
        current_start_byte = actual_end_byte + 1
        chunk_index += 1

    table.update_item(
        Key={'taskId': task_id},
        UpdateExpression="SET taskStatus = :s, totalChunks = :tc, completedChunks = :cc",
        ExpressionAttributeValues={':s': 'PROCESSING', ':tc': len(messages_to_send), ':cc': 0}
    )
    
    for msg in messages_to_send:
        sqs_client.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(msg))

    return {
        'statusCode': 200,
        'body': f'File orchestrated into {len(messages_to_send)} chunks.'
    }