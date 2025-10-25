# Request of refine the worker.py and pipeine.py

The pipeline.py as the main program, it will submit video generate request to silicon flow, 
invoke a new worker.py async function to start waiting the result.

Our text_video_silicon pipeline have worker.py, which is a back-ground thread that
poll the results from db/video_download.csv. 

It's a little bit chaos right now, these 2 jobs packed into 1 python thread. need to wait each other,
I want to split it into 2 thread. One is the main thread of pipeline, submit video, and if it's inQUeue or 
Submitted afterwards, then goes to the next block, if it return Wrong, or Too many request. It will retry.

Second thread is worker's background thread, it will chronos poll the result from db and log into ./log folder.

After the entire pipeline finished, it will set a timer to wait for the worker poll all video
downloaded. when all video's are done, then return.
