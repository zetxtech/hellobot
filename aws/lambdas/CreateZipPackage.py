import json
import boto3
import os
import io
import zipfile
import urllib.parse
from botocore.exceptions import ClientError

s3_client = boto3.client('s3')
PROCESSED_INDIVIDUAL_BUCKET = os.environ['PROCESSED_INDIVIDUAL_BUCKET'] 
PACKAGED_RESULTS_BUCKET = os.environ['PACKAGED_RESULTS_BUCKET'] 

def lambda_handler(event, context):
    try:
        body = json.loads(event.get('body', '{}'))
        files_to_package = body.get('files', [])

        if not files_to_package:
            return {
                'statusCode': 400,
                'body': json.dumps({'message': 'No files specified for packaging.'})
            }

        in_memory_zip = io.BytesIO()

        with zipfile.ZipFile(in_memory_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for file_info in files_to_package:
                s3_url = file_info.get('s3Url')
                zip_filename = file_info.get('filename', 'unknown-file.txt') 
                
                try:
                    parsed_url = urllib.parse.urlparse(s3_url)
                    s3_key = parsed_url.path.lstrip('/')
                    s3_object = s3_client.get_object(Bucket=PROCESSED_INDIVIDUAL_BUCKET, Key=s3_key)
                    file_content = s3_object['Body'].read()
                    zf.writestr(zip_filename, file_content)

                except ClientError as e:
                    print(f"Could not retrieve file for zipping: {s3_key}. Error: {e}")
                    continue
        
        in_memory_zip.seek(0)

        zip_key = f"package-{context.aws_request_id}.zip"

        s3_client.put_object(
            Bucket=PACKAGED_RESULTS_BUCKET,
            Key=zip_key,
            Body=in_memory_zip,
            ContentType='application/zip'
        )
        
        download_url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': PACKAGED_RESULTS_BUCKET, 'Key': zip_key},
            ExpiresIn=600
        )

        return {
            'statusCode': 200,
            'headers': {'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/json'},
            'body': json.dumps({'downloadUrl': download_url})
        }

    except Exception as e:
        print(f"Error creating zip package: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'message': f'Internal server error: {str(e)}'})
        }
