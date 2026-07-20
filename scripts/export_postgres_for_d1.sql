\pset tuples_only on
\pset format unaligned

SELECT format(
    'INSERT INTO tweets ('
    'tweet_id, query, user_handle, user_name, text, link, '
    'tweet_created_at, delivery_status, filter_reasons, fetched_at'
    ') VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) '
    'ON CONFLICT(link) DO UPDATE SET '
    'tweet_id = excluded.tweet_id, '
    'query = excluded.query, '
    'user_handle = excluded.user_handle, '
    'user_name = excluded.user_name, '
    'text = excluded.text, '
    'tweet_created_at = excluded.tweet_created_at, '
    'delivery_status = excluded.delivery_status, '
    'filter_reasons = excluded.filter_reasons, '
    'fetched_at = excluded.fetched_at;',
    CASE WHEN tweet_id IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(tweet_id, 'UTF8'), 'hex')) END,
    CASE WHEN query IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(query, 'UTF8'), 'hex')) END,
    CASE WHEN user_handle IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(user_handle, 'UTF8'), 'hex')) END,
    CASE WHEN user_name IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(user_name, 'UTF8'), 'hex')) END,
    CASE WHEN text IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(text, 'UTF8'), 'hex')) END,
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(link, 'UTF8'), 'hex')),
    CASE WHEN tweet_created_at IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(tweet_created_at::text, 'UTF8'), 'hex')) END,
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(delivery_status, 'UTF8'), 'hex')),
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(to_json(filter_reasons)::text, 'UTF8'), 'hex')),
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(fetched_at::text, 'UTF8'), 'hex'))
)
FROM tweets
ORDER BY id;

SELECT format(
    'INSERT INTO news ('
    'link, source, news_created_at, delivery_status, fetched_at'
    ') VALUES (%s, %s, %s, ''sent'', %s) '
    'ON CONFLICT(link) DO UPDATE SET '
    'source = excluded.source, '
    'news_created_at = excluded.news_created_at, '
    'delivery_status = excluded.delivery_status, '
    'fetched_at = excluded.fetched_at;',
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(link, 'UTF8'), 'hex')),
    CASE WHEN source IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(source, 'UTF8'), 'hex')) END,
    CASE WHEN news_created_at IS NULL THEN 'NULL'
         ELSE format('CAST(X''%s'' AS TEXT)', encode(convert_to(news_created_at::text, 'UTF8'), 'hex')) END,
    format('CAST(X''%s'' AS TEXT)', encode(convert_to(fetched_at::text, 'UTF8'), 'hex'))
)
FROM news
ORDER BY id;
