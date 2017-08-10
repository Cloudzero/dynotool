import json
import timeit
import io
import os

import boto3
import time
from botocore.exceptions import ClientError


def dump_table_launcher(event, context):
    namespace = os.environ['NAMESPACE']
    lam = boto3.client('lambda')
    payload = {'s3_bucket': event['s3_bucket'],
               'src_table': event['src_table']}

    total_segments = int(event.get('total_segments'))

    for i in range(total_segments - 1):
        if total_segments:
            payload['total_segments'] = total_segments
            payload['segment'] = i
        lam.invoke(FunctionName='dyn-o-tool-{}-dump-table'.format(namespace),
                   InvocationType='Event',
                   Payload=json.dumps(payload))


def dump_table(event, context):
    print(event['s3_bucket'],
          event['src_table'],
          event.get('total_segments'),
          event.get('segment'))

    dynamodb = boto3.client('dynamodb')
    s3 = boto3.client('s3')

    if event.get('total_segments'):
        kwargs = {'Segment': int(event.get('segment')),
                  'TotalSegments': int(event.get('total_segments'))}
    else:
        kwargs = {}
    done = False
    request_count = 0
    rows_received = 0
    retries = 0
    start = timeit.default_timer()
    while not done:
        try:
            request_count += 1

            result = dynamodb.scan(TableName=event['src_table'],
                                   Select="ALL_ATTRIBUTES", **kwargs)

            if result.get('LastEvaluatedKey'):
                kwargs['ExclusiveStartKey'] = result.get('LastEvaluatedKey')
            else:
                done = True

            rows_received += len(result['Items'])
            contents = "\n".join([json.dumps(x, default=str) for x in result['Items']])
            data = io.StringIO(contents)
            s3.put_object(Bucket=event['s3_bucket'], Key="data{}-{}.json".format(request_count,
                                                                                 event.get('segment', 1)),
                          Body=data.read())

        except ClientError as err:
            if err.response['Error']['Code'] not in ('ProvisionedThroughputExceededException',
                                                     'ThrottlingException'):
                raise
            print('Throttling ({})'.format(retries))
            time.sleep(2 ** retries)
            retries += 1
            request_count -= 1

    stop = timeit.default_timer()
    total_time = stop - start
    avg_row_processing_time = rows_received / total_time
    print('\nExport complete: {} rows exported in {:.2f} seconds (~{:.2f} rps) '
          'in {} request(s) (segment {} of {})'.format(rows_received,
                                                       total_time,
                                                       avg_row_processing_time,
                                                       request_count,
                                                       event.get('segment', 0) + 1,
                                                       event.get('total_segments', 1)))
