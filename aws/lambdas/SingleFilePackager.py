import json
import boto3
import os
from botocore.exceptions import ClientError

s3_resource = boto3.resource('s3')
s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(os.environ['DYNAMODB_TABLE_NAME'])
UPLOAD_BUCKET = os.environ['UPLOAD_BUCKET']
PROCESSED_PARTS_BUCKET = os.environ['PROCESSED_PARTS_BUCKET']
PROCESSED_INDIVIDUAL_BUCKET = os.environ['PROCESSED_INDIVIDUAL_BUCKET']

def lambda_handler(event, context):
    task_id = event.get('taskId')
    if not task_id:
        print("FATAL: taskId not provided in the event.")
        return

    try:
        task_item = table.get_item(Key={'taskId': task_id}).get('Item', {})
        if task_item.get('taskStatus') != 'FAILED':
            original_filename = task_item.get('originalFilename', 'processed-file.txt')

            bucket = s3_resource.Bucket(PROCESSED_PARTS_BUCKET)
            
            sorted_objects = sorted(bucket.objects.filter(Prefix=f"{task_id}/"), key=lambda obj: obj.key)
            
            parts = []
            for obj in sorted_objects:
                content = obj.get()['Body'].read().decode('utf-8')
                if content:
                    parts.append(content)
            
            full_content = "\n".join(parts)
            
            processed_key = f"{task_id}/Hello-{original_filename}"
            s3_client.put_object(
                Bucket=PROCESSED_INDIVIDUAL_BUCKET,
                Key=processed_key,
                Body=full_content,
                ContentType='text/plain'
            )
            
            processed_file_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': PROCESSED_INDIVIDUAL_BUCKET, 'Key': processed_key},
                ExpiresIn=86400  # 24 hours
            )
            
            table.update_item(
                Key={'taskId': task_id},
                UpdateExpression="SET taskStatus = :s, processedFileUrl = :u",
                ExpressionAttributeValues={':s': 'COMPLETED', ':u': processed_file_url}
            )

    except Exception as e:
        print(f"Error packaging single file for task {task_id}: {e}")
        table.update_item(
            Key={'taskId': task_id},
            UpdateExpression="SET taskStatus = :s",
            ExpressionAttributeValues={':s': 'FAILED'}
        )
        raise e

    finally:
        if 'sorted_objects' in locals() and sorted_objects:
            try:
                objects_to_delete = [{'Key': obj.key} for obj in sorted_objects]
                print(f"Cleaning up {len(objects_to_delete)} processed parts for task {task_id}.")
                s3_resource.meta.client.delete_objects(
                    Bucket=PROCESSED_PARTS_BUCKET,
                    Delete={'Objects': objects_to_delete}
                )
            except Exception as e:
                print(f"Error cleaning up processed parts for task {task_id}: {e}")
        
        if original_filename:
            try:
                original_file_key = f"{task_id}/{original_filename}"
                print(f"Cleaning up original file {original_file_key} from bucket {UPLOAD_BUCKET}.")
                s3_client.delete_object(Bucket=UPLOAD_BUCKET, Key=original_file_key)
            except Exception as e:
                print(f"Error cleaning up original file for task {task_id}: {e}")
