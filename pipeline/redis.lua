-- KEYS[1] = queue_key (ZSET)
-- KEYS[2] = metadata_key (HASH)
-- ARGV[1] = domain
-- ARGV[2] = priority_score (number, string format)
-- ARGV[3] = metadata_json (string)
-- ARGV[4] = queue_max_size (number, string format)

local queue_key = KEYS[1]
local metadata_key = KEYS[2]

local domain = ARGV[1]
local priority_score = tonumber(ARGV[2])
local metadata_json = ARGV[3]
local queue_max_size = tonumber(ARGV[4])

local queue_size = redis.call('ZCARD', queue_key)

if queue_size < queue_max_size then
    redis.call('ZADD', queue_key, priority_score, domain)
    redis.call('HSET', metadata_key, domain, metadata_json)
    return {1, "added"}
else
    local lowest = redis.call('ZRANGE', queue_key, 0, 0, 'WITHSCORES')
    if #lowest == 0 then
        redis.call('ZADD', queue_key, priority_score, domain)
        redis.call('HSET', metadata_key, domain, metadata_json)
        return {1, "added_empty"}
    end
    
    local lowest_domain = lowest[1]
    local lowest_score = tonumber(lowest[2])
    
    if priority_score > lowest_score then
        redis.call('ZREM', queue_key, lowest_domain)
        redis.call('HDEL', metadata_key, lowest_domain)
        
        redis.call('ZADD', queue_key, priority_score, domain)
        redis.call('HSET', metadata_key, domain, metadata_json)
        return {1, "replaced"}
    else
        return {0, "skipped"}
    end
end
