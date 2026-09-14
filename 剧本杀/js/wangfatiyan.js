		//获取主持人提示栏DOM元素
		var dl2=document.getElementById("Dialog2");
		var dl1=document.getElementById("Dialog1");
		var dl3=document.getElementById("Dialog3");
		var dl4=document.getElementById("Dialog4");
		//弹出第一个提示栏
		dl1.showModal();
		//对每个提示栏添加关闭按钮
		var dls=document.querySelectorAll("dialog");
		var btns=document.querySelectorAll(".closebutton");
		btns.forEach((btn,index)=>{
			btn.addEventListener("click",()=>{
				dls[index].close();
				if(index==0)
				{
					updateTime();//第一个提示栏关闭时开始倒计时
				}
				else if(index==1)
				{
					randomClue();//第二个关闭时随机获得线索
					updateTime();//开始倒计时
				}
				else if(index==2)
				{
					skipVote();//第三个关闭时跳转到投票界面
				}
				else if(index==3)
				{
					window.location.href="回顾总结.html";
				}
			});
		});
		
		
				let minutes = 4;
				let seconds = 0;
        const timeElement = document.getElementById('time');
        
        var count=1;
        // 计时函数
        function updateTime() {
            if(seconds==0&&minutes==0)
            {
            	if(count==1)
            	{
            		dl2.showModal();
            	    minutes=3;
            	    count++;
            	}
            	else if(count==2)
            	{
            		dl3.showModal();
            		seconds=30
            		count++;
            	}
            	else if(count==3)
            	{
            		dl4.showModal();
            		
            		count++;
            	}
            	
            }//事件停止弹出下一个提示栏
            else{
            	if(seconds<=0)
            	{
            		minutes--;
            		seconds=59;
            	}
            	else
            	{
            		seconds--;
            		
            	}
            	// 每秒更新一次时间
            	setTimeout(updateTime,1000);
            }
            //实时显示时间
            timeElement.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        }
        
		
		
		//卡片的翻转
		var imgs1=document.querySelectorAll(".p1");
		var imgs2=document.querySelectorAll(".p2");
		imgs1.forEach((img1,index)=>{
			img1.addEventListener("click",()=>{ 
				img1.style.transform="rotateY(-180deg)";
				imgs2[index].style.transform="rotateY(0deg)";
			});
		});//卡片添加点击事件使其翻转
		imgs2.forEach((img2,index)=>{
			img2.addEventListener("click",()=>{
				imgs1[index].style.transform="rotateY(0deg)";
				img2.style.transform="rotateY(180deg)";
			});
		})//添加点击事件可重新翻回来
		
		//切换投票
		var vote=document.querySelector(".vote");
		var scene=document.querySelector(".scene");
		var title=document.querySelector(".title h4")
		function skipVote(){
			vote.style.display="flex";
			scene.style.display="none";
			title.textContent="投票";
		}
		//投票选择不同的结局
		
		var choices=document.querySelectorAll(".choice");
		var end1=document.querySelector(".end1");
		var end2=document.querySelector(".end2");
		var end3=document.querySelector(".end3");
		var end4=document.querySelector(".end4");
		choices.forEach(choice=>{
			choice.addEventListener("click",()=>{
				
				if(choice.classList.contains("figure1")){
					vote.style.display="none";
					end1.style.display="flex";
					updateTime();
				}
				else if(choice.classList.contains("figure2")){
					vote.style.display="none";
					end2.style.display="flex";
					updateTime();
				}
				else if(choice.classList.contains("figure3")){
					vote.style.display="none";
					end3.style.display="flex";
					updateTime();
				}
				else if(choice.classList.contains("figure4")){
					vote.style.display="none";
					end4.style.display="flex";
					updateTime();
				}
			});
		});
		
		//随机获得线索卡
		var x=6,s=Array(12).fill(0);
		var cluesList=document.querySelector(".clues-list");
        //线索框中随机添加线索卡
		function randomClue(){
			while(x){
				var a=Math.floor(Math.random()*11)+1;
				if(s[a]==0)
				{
					var img = document.createElement("img");
					img.label=0;
		            img.src = `img/clue${a}.jpg`;
		            (function(image) {
		                image.addEventListener("click", () => {
		                    if (image.label == 0) {
		                        centerImage(image);
		                        image.label = 1;
		                    } else {
		                        restore(image);
		                        image.label = 0;
		                    }
		                });
		            })(img);//为每张线索卡绑定放大和还原事件

		            cluesList.appendChild(img);
		            s[a]=1;
		            x--;
				}
				
			}
		}
		
		//卡片放大函数
		
		function centerImage(image) {
            const screenWidth = window.innerWidth;
            const screenHeight = window.innerHeight;//获取屏幕宽高
            
            const rect = image.getBoundingClientRect(); 

		    const imageWidth = rect.width;
		    const imageHeight = rect.height;
		    const imageLeft = rect.left;
		    const imageTop = rect.top;//获取卡片宽高
		
		    const x = (screenWidth / 2) - (imageWidth / 2) - imageLeft;
		    const y = (screenHeight / 2) - (imageHeight / 2) - imageTop;//计算获得到达屏幕中央的坐标偏移
		
		    image.style.transform = `translate(${x}px, ${y}px) scale(3)`;//移动图片并放大
        }
		//卡片原来换回位置
		function restore(image) {
            const screenWidth = window.innerWidth;
            const screenHeight = window.innerHeight;
            
            const rect = image.getBoundingClientRect(); 

		    const imageWidth = rect.width;
		    const imageHeight = rect.height;
		    const imageLeft = rect.left;
		    const imageTop = rect.top;
		
		    const x = (screenWidth / 2) - (imageWidth / 2) - imageLeft;
		    const y = (screenHeight / 2) - (imageHeight / 2) - imageTop;
		
		    image.style.transform = `translate(${x}px, ${y}px) scale(1)`;//缩小为原来大小
        }